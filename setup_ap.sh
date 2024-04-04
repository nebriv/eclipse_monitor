#!/bin/bash

# Update and install necessary packages
sudo apt update
sudo apt install -y hostapd dnsmasq

# Stop services to configure them
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

sudo systemctl unmask hostapd

# Configure hostapd
cat <<EOF | sudo tee /etc/hostapd/hostapd.conf
interface=wlan0
ssid=ECLIPSEMONITOR
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=BTV-Eclipse-2024
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Tell the system where to find the hostapd configuration
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' | sudo tee -a /etc/default/hostapd

# Configure dnsmasq
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
cat <<EOF | sudo tee /etc/dnsmasq.conf
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
EOF

# Configure network interfaces
echo "interface wlan0" | sudo tee -a /etc/dhcpcd.conf
echo "static ip_address=192.168.4.1/24" | sudo tee -a /etc/dhcpcd.conf
sudo service dhcpcd restart

# Create the WiFi check script
cat <<EOF | sudo tee /usr/local/bin/check-wifi.sh
#!/bin/bash

# Wait for 120 seconds to check the WiFi connection
sleep 120

# Check WiFi connection
if ! iwgetid -r; then
    echo "WiFi not connected, switching to AP mode..."
    sudo systemctl stop wpa_supplicant
    sudo systemctl start hostapd
    sudo systemctl start dnsmasq
else
    echo "Connected to WiFi, no action required."
fi
EOF

# Make the script executable
sudo chmod +x /usr/local/bin/check-wifi.sh

# Setup systemd service for the script
cat <<EOF | sudo tee /etc/systemd/system/check-wifi.service
[Unit]
Description=Check WiFi connection and start AP if necessary
After=network.target

[Service]
ExecStart=/usr/local/bin/check-wifi.sh

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the new service
sudo systemctl enable check-wifi.service
sudo systemctl start check-wifi.service

echo "Setup complete. The system will now switch to AP mode if not connected to WiFi within 120 seconds after boot."
