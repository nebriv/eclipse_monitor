#!/usr/bin/python3

import time
import threading
import requests
import logging
import board
from adafruit_mpl3115a2 import MPL3115A2
import adafruit_ahtx0
from adafruit_sgp40 import SGP40
import adafruit_tsl2561
import spidev
from flask import Flask, render_template_string

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up Flask
app = Flask(__name__)

# In-memory log storage
log_entries = []

# Custom logging handler to store logs
class CustomLogHandler(logging.Handler):
    def emit(self, record):
        log_entries.append(self.format(record))
        if len(log_entries) > 100:  # Limit log entries to avoid memory overflow
            log_entries.pop(0)

log_handler = CustomLogHandler()
log_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.DEBUG)


INFLUXDB_URL = 'http://127.0.0.1:8086'
DATABASE_NAME = 'sensors'


def ensure_database_exists(url, db_name):
    # Check if database exists
    response = requests.get(f'{url}/query', params={'q': 'SHOW DATABASES'})
    if response.status_code != 200:
        logging.error(f"Error checking databases: {response.text}")
        return False

    if db_name in response.text:
        logging.info(f"Database '{db_name}' already exists.")
        return True

    # Create the database as it does not exist
    response = requests.post(f'{url}/query', params={'q': f'CREATE DATABASE "{db_name}"'})
    if response.status_code == 200:
        logging.info(f"Database '{db_name}' created.")
        return True
    else:
        logging.error(f"Failed to create database '{db_name}': {response.text}")
        return False


class Sensor:
    def __init__(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.samples = []
        self.lock = threading.Lock()
        self.initialized = False

    def start(self):
        if self.initialized:
            logging.debug(f"{type(self).__name__} starting thread.")
            self.thread.start()
        else:
            logging.warning(f"{type(self).__name__} not initialized properly, skipping.")

    def run(self):
        while True:
            if self.initialized:
                try:
                    self.read()
                except Exception as e:
                    logging.error(f"Error in read loop of {type(self).__name__}: {e}")
            time.sleep(self.interval())

    def read(self):
        raise NotImplementedError

    def interval(self):
        return 1

    def add_sample(self, value):
        logging.debug(f"{type(self).__name__} - adding sample {value}")
        with self.lock:
            self.samples.append(value)

    def get_average_sample(self):
        with self.lock:
            if not self.samples:
                return None

            if isinstance(self.samples[0], tuple):
                avg = tuple(sum(values) / len(values) for values in zip(*self.samples))
            else:
                avg = sum(self.samples) / len(self.samples)

            self.samples.clear()
            return avg

    def post_data(self, measurement, value, sensor_name):
        if value is not None:

            try:
                data_template = f"{measurement},sensor={sensor_name} value={value:.1f} {int(time.time()*1e9)}"
                r = requests.post(f"{INFLUXDB_URL}/write?db={DATABASE_NAME}", data=data_template)

                logging.debug(f"Response Code: {r.status_code} - Response Data: {r.text}")
                logging.info(f"{measurement} from {sensor_name} = {value:.1f}")
            except Exception as e:
                logging.error(f"Error posting data for {sensor_name}: {e}")

    def process_and_post_data(self):
        try:
            avg = self.get_average_sample()
            if avg is not None:
                self.post_data("value", avg, type(self).__name__)
        except Exception as e:
            logging.error(f"Error processing or posting data for {type(self).__name__}: {e}")

class MCP3008:
    def __init__(self, bus=0, device=0):
        self.bus, self.device = bus, device
        self.spi = spidev.SpiDev()
        self.open()
        self.spi.max_speed_hz = 1000000  # 1MHz

    def open(self):
        self.spi.open(self.bus, self.device)
        self.spi.max_speed_hz = 1000000  # 1MHz

    def read(self, channel=0):
        adc = self.spi.xfer2([1, (8 + channel) << 4, 0])
        data = ((adc[1] & 3) << 8) + adc[2]
        return data

    def close(self):
        self.spi.close()

class UVSensor(Sensor):
    CALIBRATION_OFFSET = 82  # Set your calibration offset here

    def __init__(self, channel=0):
        super().__init__()
        self.channel = channel
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)  # Assuming bus=0, device=0 for MCP3008
        self.spi.max_speed_hz = 1000000
        self.initialized = True

    def read(self):
        if not self.initialized:
            return

        try:
            adc = self.spi.xfer2([1, (8 + self.channel) << 4, 0])
            data = ((adc[1] & 3) << 8) + adc[2]
            raw_value = data
            print(f"Raw: {raw_value}")
            calibrated_value = max(0, raw_value - UVSensor.CALIBRATION_OFFSET)
            voltage = (calibrated_value * 3.3) / 1023  # Assuming a 3.3V reference voltage
            uv_index = voltage / 0.1
            self.add_sample(uv_index)
        except Exception as e:
            logging.error(f"Error reading from UV sensor: {e}")

    def close(self):
        self.spi.close()

    def __del__(self):
        self.close()

class MPLPressureSensor(Sensor):
    def __init__(self):
        super().__init__()
        try:
            self.sensor = MPL3115A2(board.I2C())
            self.initialized = True
        except Exception as e:
            logging.error(f"Failed to initialize MPL3115A2 sensor: {e}")

    def read(self):
        if not self.initialized:
            return
        try:
            pressure = self.sensor.pressure
            self.add_sample(pressure)
        except Exception as e:
            logging.error(f"Error reading from MPL3115A2 sensor: {e}")

class MPLTemperatureSensor(Sensor):
    def __init__(self):
        super().__init__()
        try:
            self.sensor = MPL3115A2(board.I2C())
            self.initialized = True
        except Exception as e:
            logging.error(f"Failed to initialize MPL3115A2 sensor: {e}")

    def read(self):
        if not self.initialized:
            return
        try:
            pressure = self.sensor.temperature
            self.add_sample(pressure)
        except Exception as e:
            logging.error(f"Error reading from MPL3115A2 sensor: {e}")


class AHTX0BaseSensor(Sensor):
    def __init__(self):
        super().__init__()
        try:
            self.sensor = adafruit_ahtx0.AHTx0(board.I2C())
            self.initialized = True
        except Exception as e:
            logging.error(f"Failed to initialize AHTX0 sensor: {e}")

class AHTTemperatureSensor(AHTX0BaseSensor):
    def read(self):
        if not self.initialized:
            return
        try:
            temperature = self.sensor.temperature
            self.add_sample(temperature)
        except Exception as e:
            logging.error(f"Error reading temperature from AHTX0 sensor: {e}")

class AHTHumiditySensor(AHTX0BaseSensor):
    def read(self):
        if not self.initialized:
            return
        try:
            humidity = self.sensor.relative_humidity
            self.add_sample(humidity)
        except Exception as e:
            logging.error(f"Error reading humidity from AHTX0 sensor: {e}")

class SGP40Sensor(Sensor):
    def __init__(self, temperature_sensor, humidity_sensor):
        super().__init__()
        try:
            self.sensor = SGP40(board.I2C())
            self.temperature_sensor = temperature_sensor
            self.humidity_sensor = humidity_sensor
            self.initialized = True
        except Exception as e:
            logging.error(f"Failed to initialize SGP40 sensor: {e}")

    def interval(self):
        return 1 if self.initialized else 60

    def read(self):
        if not self.initialized:
            return
        try:
            temp_avg = self.temperature_sensor.get_average_sample()
            hum_avg = self.humidity_sensor.get_average_sample()
            if temp_avg is None or hum_avg is None:
                logging.warning("No data from temperature or humidity sensor yet, skipping SGP40 read.")
                return
            voc_index = self.sensor.measure_index(temperature=temp_avg, relative_humidity=hum_avg)
            self.add_sample(voc_index)
        except Exception as e:
            logging.error(f"Error reading from SGP40 sensor: {e}")

class TSL2561Sensor(Sensor):
    def __init__(self):
        super().__init__()
        try:
            self.sensor = adafruit_tsl2561.TSL2561(board.I2C())
            self.initialized = True
        except Exception as e:
            logging.error(f"Failed to initialize TSL2561 sensor: {e}")

    def read(self):
        if not self.initialized:
            return
        try:
            light = self.sensor.lux
            self.add_sample(light)
        except Exception as e:
            logging.error(f"Error reading from TSL2561 sensor: {e}")

def main():
    if not ensure_database_exists(INFLUXDB_URL, DATABASE_NAME):
        logging.error("Could not ensure database exists, check InfluxDB and try again.")
        return

    aht_temp_sensor = AHTTemperatureSensor()
    aht_hum_sensor = AHTHumiditySensor()
    sensors = [
        MPLTemperatureSensor(),
        MPLPressureSensor(),
        aht_temp_sensor,
        aht_hum_sensor,
        SGP40Sensor(aht_temp_sensor, aht_hum_sensor),
        TSL2561Sensor(),
        UVSensor(),
    ]

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    for sensor in sensors:
        sensor.start()



    while True:
        time.sleep(1)
        logging.info("Collecting data...")
        for sensor in sensors:
            try:
                sensor.process_and_post_data()
            except Exception as e:
                logging.error(f"Error during process and post data for {type(sensor).__name__}: {e}")


@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sensor Log Output</title>
        <meta http-equiv="refresh" content="5">
    </head>
    <body>
        <h1>Sensor Log Output</h1>
        <pre>{{ log_entries|join('\n') }}</pre>
    </body>
    </html>
    """, log_entries=log_entries)

def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    main()