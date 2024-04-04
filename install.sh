#!/bin/bash

sudo ./setup_ap.sh

sudo apt update
sudo apt upgrade

sudo apt install -y python3-pip hostapd dnsmasq
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt


# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

docker compose pull

docker compose up -d

sudo cp eclipse-monitor.service /etc/systemd/system/eclipse-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable eclipse-monitor.service
sudo systemctl start eclipse-monitor.service
