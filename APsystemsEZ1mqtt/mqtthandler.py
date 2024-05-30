# Author: Holger Mueller <github@euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Handle MQTT connection and data publishing"""
import atexit
import certifi
import json
import logging
import time

from APsystemsEZ1 import ReturnDeviceInfo, ReturnOutputData
from APsystemsEZ1mqtt.config import ECUConfig, MQTTConfig
from datetime import datetime
from paho.mqtt import client as mqtt_client
from paho.mqtt.enums import CallbackAPIVersion

_LOGGER = logging.getLogger(__name__)

_MAX_RETRY = 10

_homa_arr = [
    {'control': 'Power',              'type': 'text',   'room': 'Home', 'unit': ' W',   'class': 'power'},
    {'control': 'Power P1',           'type': 'text',   'room': '',     'unit': ' W',   'class': 'power'},
    {'control': 'Power P2',           'type': 'text',   'room': '',     'unit': ' W',   'class': 'power'},
    {'control': 'Energy today',       'type': 'text',   'room': 'Home', 'unit': ' kWh', 'class': 'energy'},
    {'control': 'Energy today P1',    'type': 'text',   'room': '',     'unit': ' kWh', 'class': 'energy'},
    {'control': 'Energy today P2',    'type': 'text',   'room': '',     'unit': ' kWh', 'class': 'energy'},
    {'control': 'Energy lifetime',    'type': 'text',   'room': '',     'unit': ' kWh', 'class': 'energy_increasing'},
    {'control': 'Energy lifetime P1', 'type': 'text',   'room': '',     'unit': ' kWh', 'class': 'energy_increasing'},
    {'control': 'Energy lifetime P2', 'type': 'text',   'room': '',     'unit': ' kWh', 'class': 'energy_increasing'},
    {'control': 'Power Status',       'type': 'switch', 'room': '',     'unit': '',     'class': 'switch'},
    {'control': 'Power Max Output',   'type': 'text',   'room': '',     'unit': ' kWh', 'class': 'number'},
    {'control': 'Device id',          'type': 'text',   'room': '',     'unit': '',     'class': None},
    {'control': 'Device IP',          'type': 'text',   'room': '',     'unit': '',     'class': None},
    {'control': 'Version',            'type': 'text',   'room': '',     'unit': '',     'class': None},
    {'control': 'Start time',         'type': 'text',   'room': '',     'unit': '',     'class': 'date'},
    {'control': 'State',              'type': 'text',   'room': '',     'unit': '',     'class': None},
]


class MQTTHandler:
    """Handle MQTT connection to broker and publish message"""

    def __init__(self, mqtt_config: MQTTConfig):
        self.mqtt_config = mqtt_config
        self.client = None


    def on_connect(self, client, userdata, flags, rc):
        """Callback function on broker connection"""
        del client, userdata, flags
        if rc == 0:
            _LOGGER.info("Connected to MQTT Broker!")
        else:
            _LOGGER.error("Failed to connect: %s", mqtt_client.connack_string(rc))


    def on_disconnect(self, client, userdata, rc):
        """Callback function on broker disconnection"""
        del client, userdata
        _LOGGER.info("Disconnected from MQTT Broker: %s", mqtt_client.error_string(rc))


    def _publish(self, client, topic: str, msg: mqtt_client.PayloadType, qos: int = 0, retain: bool = False):
        result = client.publish(topic, msg, qos, retain)
        status = result[0]
        if status == 0:
            _LOGGER.debug("Send `%s` to topic `%s`", msg, topic)
        else:
            _LOGGER.error(
                "Failed to send message to topic %s: %s", topic, mqtt_client.error_string(status)
            )


    def connect_mqtt(self):
        """Create connection to MQTT broker"""
        _LOGGER.debug("Create MQTT client")
        self.client = mqtt_client.Client(CallbackAPIVersion.VERSION1, self.mqtt_config.client_id, 
                                         clean_session=False if self.mqtt_config.client_id else True)

        if len(self.mqtt_config.broker_user.strip()) > 0:
            _LOGGER.debug("Connect with user '%s'", self.mqtt_config.broker_user)
            self.client.username_pw_set(
                self.mqtt_config.broker_user, self.mqtt_config.broker_passwd
            )
        else:
            _LOGGER.debug("Connect anonymously")

        if self.mqtt_config.secured_connection:
            _LOGGER.debug("Use secured connection")
            if self.mqtt_config.cacerts_path is None:
                _LOGGER.warning("No ca_certs defined, using default one")

            self.client.tls_set(
                ca_certs=(
                    self.mqtt_config.cacerts_path
                    if self.mqtt_config.cacerts_path is not None
                    else certifi.where()
                )
            )
        else:
            _LOGGER.debug("Use unsecured connection")

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

        _LOGGER.info(
            "Connect to broker '%s' on port %s",
            self.mqtt_config.broker_addr,
            self.mqtt_config.broker_port,
        )
        self.client.connect_async(self.mqtt_config.broker_addr, self.mqtt_config.broker_port)
        self.client.loop_start()
        atexit.register(self.client.loop_stop)


    def _check_mqtt_connected(self):
        """Check MQTT broker connection"""
        retry_count = 0
        while not self.client.is_connected() and retry_count < _MAX_RETRY:
            _LOGGER.debug("MQTT client not connected...")
            retry_count += 1
            time.sleep(5)

        if retry_count == _MAX_RETRY:
            _LOGGER.warning("MQTT values not published")
            raise ConnectionError("Can't connect to broker")


    def publish_data(self, data):
        """Publish ECU data to MQTT"""
        _LOGGER.debug("Start MQTT publish")
        self._check_mqtt_connected()

        for topic, value in self._parse_data(data).items():
            self._publish(self.client, topic, value, 1, False)
        _LOGGER.debug("MQTT values published")


    def _parse_data(self, data: ReturnOutputData):
        """
        Parse data from APsystemsEZ1 ReturnOutputData
        The data include power output status ('p1', 'p2'), energy readings ('e1', 'e2'), and total energy ('te1', 'te2')
        """
        output = {}
        if self.mqtt_config.homa_enabled:
            topic_base = "/devices/" + self.mqtt_config.homa_systemid + "/controls/" # e.g. "/devices/123456-solar/controls/"
        else:
            topic_base = self.mqtt_config.topic_prefix  # e.g. "/aps/"
        output[topic_base + "Power"] = f'{(data.p1 + data.p2):d}'
        output[topic_base + "Power P1"] = f'{data.p1:d}'
        output[topic_base + "Power P2"] = f'{data.p2:d}'
        output[topic_base + "Energy today"] = f'{(data.e1 + data.e2):0.3f}'
        output[topic_base + "Energy today P1"] = f'{data.e1:0.3f}'
        output[topic_base + "Energy today P2"] = f'{data.e2:0.3f}'
        output[topic_base + "Energy lifetime"] = f'{(data.te1 + data.te2):0.3f}'
        output[topic_base + "Energy lifetime P1"] = f'{data.te1:0.3f}'
        output[topic_base + "Energy lifetime P2"] = f'{data.te2:0.3f}'
        return output


    def homa_init(self, ecu_info: ReturnDeviceInfo, tz):
        """Publish HomA init messages to MQTT"""
        _LOGGER.debug("Start homa_init")

        if not self.mqtt_config.homa_enabled:
            _LOGGER.debug("HomA not enabled. Stopping here.")
            return

        self._check_mqtt_connected()

        retain = False
        qos = 1
        topic_base = "/devices/" + self.mqtt_config.homa_systemid + "/" # e.g. "/devices/123456-solar/"

        self._publish(self.client, topic_base + "meta/name", self.mqtt_config.homa_name, qos, retain)
        self._publish(self.client, topic_base + "meta/room", self.mqtt_config.homa_room, qos, retain)

        # setup controls
        topic_base += "controls/" # e.g. "/devices/123456-solar/controls/"
        order = 1
        for homa in _homa_arr:
            self._publish(self.client, topic_base + homa['control'] + "/meta/type", homa['type'], qos, retain)
            self._publish(self.client, topic_base + homa['control'] + "/meta/order", order, qos, retain)
            self._publish(self.client, topic_base + homa['control'] + "/meta/room", homa['room'], qos, retain)
            self._publish(self.client, topic_base + homa['control'] + "/meta/unit", homa['unit'], qos, retain)
            order += 1

        self._publish(self.client, topic_base + "Device id", ecu_info.deviceId, qos, retain)
        self._publish(self.client, topic_base + "Device IP", ecu_info.ipAddr, qos, retain)
        self._publish(self.client, topic_base + "Version", ecu_info.devVer, qos, retain)
        #self._publish(self.client, topic_base + "Start time", time.asctime(time.localtime(time.time())), qos, retain) # not ISO 8601 compliant
        self._publish(self.client, topic_base + "Start time", datetime.now(tz).isoformat(timespec='seconds'), qos, retain)
        self._publish(self.client, topic_base + "State", "online", qos, retain)

        _LOGGER.debug("HomA MQTT values published")


    def hass_init(self, ecu_config: ECUConfig, ecu_info: ReturnDeviceInfo):
        "Send the Home Assistant config messages to enable discovery"
        _LOGGER.debug("Start homeassistant_init")

        if not self.mqtt_config.hass_enabled:
            _LOGGER.debug("Home Assistant not enabled. Stopping here.")
            return

        self._check_mqtt_connected()
        for homa in _homa_arr:
            self._hass_config(homa, ecu_config, ecu_info)


    def _hass_config(self, dict, ecu_config: ECUConfig, ecu_info: ReturnDeviceInfo):
        """Send a single Home Assistant config message to enable discovery"""
        retain = False
        qos = 1

        if dict['class'] is None:
            return

        object_id = self.mqtt_config.hass_device_id + "-" + dict['control'].replace(" ", "-")
        if self.mqtt_config.homa_enabled:
            state_topic = "/devices/" + self.mqtt_config.homa_systemid + "/controls/" + dict['control']
        else:
            state_topic = self.mqtt_config.topic_prefix + dict['control']

        # topic: <discovery_prefix>/<component>/[<node_id>/]<object_id>/config
        topic = "homeassistant/sensor/" + object_id + "/config"

        payload = {
            "name":self.mqtt_config.hass_name_prefix + dict['control'],
            "state_topic":state_topic,
            "unique_id":object_id,
            "object_id":object_id,
            "device":{
                "identifiers":[self.mqtt_config.hass_device_id],
                "name":"PV Solar Balkonkraftwerk",
                "manufacturer":"APsystems",
                "model":"EZ1",
                "configuration_url":"http://" + ecu_config.ipaddr + ":" + str(ecu_config.port) + "/getAlarm",
                "suggested_area":self.mqtt_config.hass_area,
                 #"serial_number":ecu_info.deviceId, # is broken at HA 2023.7.3, if used discover messages do not work
                "sw_version":ecu_info.devVer
            }
        }
        # add unit, if there is one
        if dict['unit']:
            payload['unit_of_measurement'] = dict['unit']

        # special handling depending on dict['class']
        if dict['class'] == "energy_increasing":
            payload['device_class'] = "energy"
            payload['state_class'] = "total_increasing"
        elif dict['class'] == "number":
            payload['command_topic'] = state_topic
            payload['mode'] = "box"
            payload['icon'] = "mdi:lightning-bolt-outline"
            topic = "homeassistant/number/" + object_id + "/config"
        elif dict['class'] == "switch":
            payload['command_topic'] = state_topic + "/on"
            payload['payload_off'] = "0"
            payload['payload_on'] = "1"
            topic = "homeassistant/switch/" + object_id + "/config"
        elif dict['class'] == "date":
            #payload['device_class'] = "date" # do not set date class, as output cuts time
            payload['value_template'] = "{{ as_datetime(value) }}"
            payload['icon'] = "mdi:calendar-arrow-right"
        else:
            payload['device_class'] = dict['class']

        self._publish(self.client, topic, json.dumps(payload), qos, retain)
