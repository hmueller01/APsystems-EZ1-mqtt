[![Maintenance badge](https://img.shields.io/maintenance/yes/2024)](https://github.com/hmueller01/APsystems-EZ1-mqtt)
[![Release badge](https://img.shields.io/github/v/release/hmueller01/APsystems-EZ1-mqtt)](https://github.com/hmueller01/APsystems-EZ1-mqtt/releases)

# APsystems EZ1 MQTT gateway

This component is a Python module to gateway [APsystems](https://apsystems.com/) EZ1 inverter local API to MQTT, [HomA](https://github.com/binarybucks/homA) and [Home Assistant](https://www.home-assistant.io).


## Acknowledgements

This work is based on [aps2mqtt (v1.2.0)](https://github.com/fligneul/aps2mqtt). Thanks for your work @fligneul!

## Basic Requirements
* Python >= 3.11
* MQTT broker (e.g. [Eclipse Mosquitto](https://github.com/eclipse/mosquitto))
* [APsystems EZ1 inverter](https://emea.apsystems.com/diy/)

## Prerequisites

The access to the local API is done by the [APsystems-EZ1-API](https://github.com/SonnenladenGmbH/APsystems-EZ1-API). Please configure the EZ1 inverter as described there.

## Installation

Binaries are available in the release asset or on [PyPI](https://pypi.org/project/APsystems-EZ1-mqtt/).
Using a virtual env is recommended for better insulation.

``` sh
pip3 install APsystems-EZ1-mqtt
```

Alternatively a [github release](https://github.com/hmueller01/APsystems-EZ1-mqtt/releases) can be downloaded or cloned and the dependencies installed manually.

``` sh
clone https://github.com/hmueller01/APsystems-EZ1-mqtt
cd APsystems-EZ1-mqtt
python3.11 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
```

Start it
``` sh
python3 -m APsystemsEZ1mqtt -h
```

### Run as a service

Using systemd, APsystems-EZ1-mqtt can be started automatically

``` yaml
[Unit]
Description=APsystems-EZ1-mqtt
After=multi-user.target

[Service]
Type=simple
User=user
Restart=on-failure
ExecStart=/path-to-your-venv/python3 -m APsystemsEZ1mqtt -c config.yaml

[Install]
WantedBy=multi-user.target
```

## Configuration

APsystems-EZ1-mqtt configuration can be provided by a yaml config file or by environment variables (in a container context for example).

Using the yaml config you can copy provided template `config-template.yaml` e.g. to `config.yaml`.

Config at least the IP of the APsystems EZ1 inverter (`APS_ECU_IP`) and the MQTT broker settings (`MQTT_BROKER_*`).

If you do not need the [HomA](https://github.com/binarybucks/homA) environment you can set `HOMA_ENABLED: False`.

If you do not need [Home Assistant](https://www.home-assistant.io) you can set `HASS_ENABLED: False`.

### ECU

| Key | Description | Example | Default value |
|---|---|---|---|
| APS_ECU_IP | IP of the ECU | "192.168.0.42" | None, this field id mandatory |
| APS_ECU_PORT | Communication port of the ECU | 8050 | 8050 |
| APS_ECU_UPDATE_INTERVAL | Time between the update polls | 60 | 15 |
| APS_ECU_STOP_AT_NIGHT | Stop ECU query during the night | True | False |
| APS_ECU_POSITION_LAT | Latitude of the ECU, used to retrieve sunset and sunrise <br />:information_source: Only used if stop at night is enabled | 51.49819 | 52.5162 (Berlin) |
| APS_ECU_POSITION_LNG | Longitude of the ECU, used to retrieve sunset and sunrise <br />:information_source: Only used if stop at night is enabled | -0.13087 | 13.3777 (Berlin) |
| APS_ECU_TIMEZONE | Timezone of the ECU | "Europe/Berlin" | None (use system timezone) |

### MQTT

| Key | Description | Example | Default value |
|---|---|---|---|
| MQTT_BROKER_HOST | Host of the MQTT broker | "broker.hivemq.com" | "127.0.0.1" |
| MQTT_BROKER_PORT | Port of the MQTT broker | 8883 | 1883 |
| MQTT_BROKER_USER | User login of the MQTT broker | "john-deere" | "" |
| MQTT_BROKER_PASSWD | User password of the MQTT broker | "secret" | "" |
| MQTT_BROKER_SECURED_CONNECTION | Use secure connection to MQTT broker | True | False |
| MQTT_BROKER_CACERTS_PATH | Path to the cacerts file | "/home/jd/.ssl/cacerts" | None |
| MQTT_CLIENT_ID | Client ID if the MQTT client | "foo" | "" |
| MQTT_TOPIC_PREFIX | Topic prefix for publishing <br />:information_source: Only used if HomA is disabled | "/aps/" | "" |
| |
| HOMA_ENABLED| Enable HomA MQTT messages | False | True |
| HOMA_SYSTEMID| HomA system id <br />:information_source: Use inverter id if empty | "123456-solar" | '' |
| HOMA_ROOM| HomA room to show data | "PV" | "Sensors" |
| HOMA_NAME| HomA name | "My PV System" | "Solar PV" |
| |
| HASS_ENABLED| Enable Home Assistant MQTT messages | True | False |
| HASS_DEVICE_ID| Home Assistant id <br />:information_source: Use inverter id if empty |  | "" |
| HASS_DEVICE_NAME| Home Assistant device name | "Solar PV Balkonkraftwerk" | "Solar PV" |
| HASS_NAME_PREFIX| Home Assistant name prefix | "Solar " | "" |
| HASS_AREA| Home Assistant area name | "My PV System" | "Energie" |

### Timezone

Without any specific configuration, APsystems-EZ1-mqtt uses your system's timezone as a reference.

* It is recommented setting the timezone by the configuration variable `APS_ECU_TIMEZONE` for better processing.

* Alternatively, if set, the environement variable `TZ` is used.

## MQTT topics

The APsystems-EZ1-mqtt topics depend on the configuration. If HomA is deactivated (`HOMA_ENABLED: False`) topics start with [MQTT_TOPIC_PREFIX], otherwise "/devices/[HOMA_SYSTEMID]/controls/" will be used.

* [topic start]Power - total amount of power (in W) being generated right now
* [topic start]Power P1 - power of channel 1 (in W) being generated right now
* [topic start]Power P2 - power of channel 2 (in W) being generated right now
* [topic start]Energy today - total amount of energy (in kWh) generated today
* [topic start]Energy today P1 - channel 1 amount of energy (in kWh) generated today
* [topic start]Energy today P2 - channel 2 amount of energy (in kWh) generated today
* [topic start]Energy lifetime - total lifetime amount of energy (in kWh) generated
* [topic start]Energy lifetime P1 - channel 1 lifetime amount of energy (in kWh) generated
* [topic start]Energy lifetime P2 - channel 2 lifetime amount of energy (in kWh) generated

If Home Assistant is enabled (`HASS_ENABLED: True`) Home Assistant auto config messages will be generated, like: "homeassistant/sensor/[object_id]/config"
