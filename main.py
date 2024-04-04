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

# Initialize logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
                r = requests.post("http://127.0.0.1:8086/write?db=sensors", data=data_template)

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
    aht_temp_sensor = AHTTemperatureSensor()
    aht_hum_sensor = AHTHumiditySensor()
    sensors = [
        MPLTemperatureSensor(),
        MPLPressureSensor(),
        aht_temp_sensor,
        aht_hum_sensor,
        SGP40Sensor(aht_temp_sensor, aht_hum_sensor),
        TSL2561Sensor(),
    ]

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

if __name__ == "__main__":
    main()