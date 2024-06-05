# Author: Holger Mueller <github euhm.de>
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

# amount of max retries to connect to the MQTT broker
_MAX_RETRY = 10

# dictionary of MQTT messages and HomA / Home Assistant configuration
# 'topic' is the last part of the topic that is send
# 'type', 'room' and 'unit' is needed by HomA
# 'unit', 'comp' (component part of the discovery topic, do not send topic if None) and 'class' (device_class, do not set if None) is needed by Home Assistant
_mqtt_d = {
    'pt': {'topic': 'Power',              'type': 'text',   'room': 'Home', 'unit': ' W',   'comp': 'sensor', 'class': 'power'},
    'p1': {'topic': 'Power P1',           'type': 'text',   'room': '',     'unit': ' W',   'comp': 'sensor', 'class': 'power'},
    'p2': {'topic': 'Power P2',           'type': 'text',   'room': '',     'unit': ' W',   'comp': 'sensor', 'class': 'power'},
    'et': {'topic': 'Energy today',       'type': 'text',   'room': 'Home', 'unit': ' kWh', 'comp': 'sensor', 'class': 'energy'},
    'e1': {'topic': 'Energy today P1',    'type': 'text',   'room': '',     'unit': ' kWh', 'comp': 'sensor', 'class': 'energy'},
    'e2': {'topic': 'Energy today P2',    'type': 'text',   'room': '',     'unit': ' kWh', 'comp': 'sensor', 'class': 'energy'},
    'lt': {'topic': 'Energy lifetime',    'type': 'text',   'room': '',     'unit': ' kWh', 'comp': 'sensor', 'class': '_energy_increasing'},
    'l1': {'topic': 'Energy lifetime P1', 'type': 'text',   'room': '',     'unit': ' kWh', 'comp': 'sensor', 'class': '_energy_increasing'},
    'l2': {'topic': 'Energy lifetime P2', 'type': 'text',   'room': '',     'unit': ' kWh', 'comp': 'sensor', 'class': '_energy_increasing'},
    'ps': {'topic': 'Power Status',       'type': 'switch', 'room': '',     'unit': '',     'comp': 'switch', 'class': None},
    'po': {'topic': 'Power Max Output',   'type': 'text',   'room': '',     'unit': ' W',   'comp': 'number', 'class': 'power', 'min': 30, 'max': 800},
    'id': {'topic': 'Device id',          'type': 'text',   'room': '',     'unit': '',     'comp': None,     'class': None},
    'ip': {'topic': 'Device IP',          'type': 'text',   'room': '',     'unit': '',     'comp': None,     'class': None},
    've': {'topic': 'Version',            'type': 'text',   'room': '',     'unit': '',     'comp': None,     'class': None},
    'ti': {'topic': 'Start time',         'type': 'text',   'room': '',     'unit': '',     'comp': 'sensor', 'class': '_datetime'},
    'wi': {'topic': 'State',              'type': 'text',   'room': '',     'unit': '',     'comp': None,     'class': None}, # last will topic
}

class MQTTHandler:
    """Handle MQTT connection to broker and publish message"""

    def __init__(self, trigger_on_status_power, trigger_async_on_max_power, mqtt_config: MQTTConfig, qos: int = 1, retain = False):
        self.mqtt_config = mqtt_config
        self.qos = qos
        self.retain = retain
        self.trigger_async_on_status_power = trigger_on_status_power
        self.trigger_async_on_max_power = trigger_async_on_max_power
        self.client = None


    def on_connect(self, client, userdata, flags, rc):
        """Callback function on broker connection"""
        del userdata, flags
        
        # Subscribe to topics with specific callbacks
        topic_base = self._get_topic_base()
        client.subscribe(topic_base + _mqtt_d['ps']['topic'] + "/on")
        client.subscribe(topic_base + _mqtt_d['po']['topic'] + "/on")
        if rc == 0:
            _LOGGER.info("Successfully connected to MQTT Broker.")
        else:
            _LOGGER.error("Failed to connect: %s", mqtt_client.connack_string(rc))


    def on_disconnect(self, client, userdata, rc):
        """Callback function on broker disconnection"""
        del client, userdata
        _LOGGER.info("Disconnected from MQTT Broker: %s", mqtt_client.error_string(rc))


    def on_status_power(self, client, userdata, message: mqtt_client.MQTTMessage):
        """Callback function on power status change (switch on or off)"""
        _LOGGER.debug("Received `%s` on topic `%s` (qos=%d, retain=%r)", message.payload.decode(), message.topic, message.qos, message.retain)
        status_map = {"0": False, "off": False, "false": False, "1": True, "on": True, "true": True}
        status = status_map.get(message.payload.decode().lower())
        if status is None:
            raise ValueError(
                f"Invalid power status: expected '0', 'ON' or '1', 'OFF', got '{message.payload.decode()}'")
        # create a task in the main event loop
        self.trigger_async_on_status_power(status)


    def on_max_power(self, client, userdata, message: mqtt_client.MQTTMessage):
        """Callback function on max power change"""
        _LOGGER.debug("Received `%s` on topic `%s` (qos=%d, retain=%r)", message.payload.decode(), message.topic, message.qos, message.retain)
        # create a task in the main event loop
        self.trigger_async_on_max_power(int(message.payload.decode()))


    def _publish(self, client, topic: str, msg: mqtt_client.PayloadType, qos: int = 0, retain: bool = False):
        result = client.publish(topic, msg, qos, retain)
        status = result[0]
        if status == 0:
            _LOGGER.debug("Send `%s` to topic `%s` (qos=%d, retain=%r)", msg, topic, qos, retain)
        else:
            _LOGGER.error("Failed to send message to topic %s: %s", topic, mqtt_client.error_string(status))


    def _get_topic_base(self) -> str:
        """
        Get the base topic string depending on HomA enabled.
        
        e.g. "/devices/123456-solar/controls/" (using mqtt_config.homa_systemid) or "aps/ (using mqtt_config.topic_prefix)"
        """
        if self.mqtt_config.homa_enabled:
            topic_base = "/devices/" + self.mqtt_config.homa_systemid + "/controls/"
        else:
            topic_base = self.mqtt_config.topic_prefix
        return topic_base


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

        self.client.will_set(_mqtt_d['wi']['topic'], "offline", 1, True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        
        # add callback for power status switch
        topic_base = self._get_topic_base()
        topic = topic_base + _mqtt_d['ps']['topic'] + "/on"
        self.client.message_callback_add(topic, self.on_status_power)
        topic = topic_base + _mqtt_d['po']['topic'] + "/on"
        self.client.message_callback_add(topic, self.on_max_power)

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


    def publish_max_power(self, max_power: int | None):
        """Publish ECU max power data to MQTT"""
        _LOGGER.debug(f"Start publish_max_power(max_power={max_power})")
        self._check_mqtt_connected()
        topic_base = self._get_topic_base()
        if max_power is not None:
            self._publish(self.client, topic_base + _mqtt_d['po']['topic'], 
                          max_power, self.qos, self.retain)


    def publish_status_power(self, status: bool | None):
        """Publish ECU power status to MQTT"""
        _LOGGER.debug(f"Start publish_status_power(status={status})")
        self._check_mqtt_connected()
        topic_base = self._get_topic_base()
        if status is not None:
            self._publish(self.client, topic_base + _mqtt_d['ps']['topic'], 
                          "1" if status else "0", self.qos, self.retain)


    def publish_data(self, data):
        """Publish ECU data to MQTT"""
        _LOGGER.debug("Start MQTT publish")
        self._check_mqtt_connected()

        if data is not None:
            for topic, value in self._parse_data(data).items():
                self._publish(self.client, topic, value, self.qos, self.retain)
            _LOGGER.debug("MQTT values published")


    def _parse_data(self, data: ReturnOutputData):
        """
        Parse data from APsystemsEZ1 ReturnOutputData
        The data include power output status ('p1', 'p2'), energy readings ('e1', 'e2'), and total energy ('te1', 'te2')
        """
        output = {}
        topic_base = self._get_topic_base()
        output[topic_base + _mqtt_d['pt']['topic']] = f'{(data.p1 + data.p2):d}'
        output[topic_base + _mqtt_d['p1']['topic']] = f'{data.p1:d}'
        output[topic_base + _mqtt_d['p2']['topic']] = f'{data.p2:d}'
        output[topic_base + _mqtt_d['et']['topic']] = f'{(data.e1 + data.e2):0.3f}'
        output[topic_base + _mqtt_d['e1']['topic']] = f'{data.e1:0.3f}'
        output[topic_base + _mqtt_d['e2']['topic']] = f'{data.e2:0.3f}'
        output[topic_base + _mqtt_d['lt']['topic']] = f'{(data.te1 + data.te2):0.1f}'
        output[topic_base + _mqtt_d['l1']['topic']] = f'{data.te1:0.1f}'
        output[topic_base + _mqtt_d['l2']['topic']] = f'{data.te2:0.1f}'
        return output


    def homa_init(self, ecu_info: ReturnDeviceInfo, tz):
        """Publish HomA init messages to MQTT"""
        _LOGGER.debug("Start homa_init")

        if not self.mqtt_config.homa_enabled:
            _LOGGER.debug("HomA not enabled. Stopping here.")
            return

        self._check_mqtt_connected()

        # setup controls
        topic_base = self._get_topic_base()
        order = 1
        for key, homa in _mqtt_d.items():
            self._publish(self.client, topic_base + homa['topic'] + "/meta/type", homa['type'], self.qos, self.retain)
            self._publish(self.client, topic_base + homa['topic'] + "/meta/order", order, self.qos, self.retain)
            self._publish(self.client, topic_base + homa['topic'] + "/meta/room", homa['room'], self.qos, self.retain)
            self._publish(self.client, topic_base + homa['topic'] + "/meta/unit", homa['unit'], self.qos, self.retain)
            order += 1

        self._publish(self.client, topic_base + _mqtt_d['id']['topic'], ecu_info.deviceId, self.qos, self.retain)
        self._publish(self.client, topic_base + _mqtt_d['ip']['topic'], ecu_info.ipAddr, self.qos, self.retain)
        self._publish(self.client, topic_base + _mqtt_d['ve']['topic'], ecu_info.devVer, self.qos, self.retain)
        self._publish(self.client, topic_base + _mqtt_d['ti']['topic'], datetime.now(tz).isoformat(timespec='seconds'), self.qos, self.retain)
        self._publish(self.client, topic_base + _mqtt_d['wi']['topic'], "online", self.qos, self.retain) # last will as long as connected

        topic_base = topic_base.replace("/controls/", "/meta/")
        self._publish(self.client, topic_base + "name", self.mqtt_config.homa_name, self.qos, self.retain)
        self._publish(self.client, topic_base + "room", self.mqtt_config.homa_room, self.qos, self.retain)
        
        _LOGGER.debug("HomA MQTT values published")


    def hass_init(self, ecu_config: ECUConfig, ecu_info: ReturnDeviceInfo):
        "Send the Home Assistant config messages to enable discovery"
        _LOGGER.debug("Start homeassistant_init")

        if not self.mqtt_config.hass_enabled:
            _LOGGER.debug("Home Assistant not enabled. Stopping here.")
            return

        self._check_mqtt_connected()
        for key, homa in _mqtt_d.items():
            self._hass_config(homa, ecu_config, ecu_info)


    def _hass_config(self, dict, ecu_config: ECUConfig, ecu_info: ReturnDeviceInfo):
        """Send a single Home Assistant config message to enable discovery"""
        if dict['comp'] is None:
            return

        object_id = self.mqtt_config.hass_device_id + "-" + dict['topic'].replace(" ", "-")
        state_topic = self._get_topic_base() + dict['topic']

        # topic: <discovery_prefix>/<component>/[<node_id>/]<object_id>/config
        topic = "/".join(["homeassistant", dict['comp'], object_id, "config"])

        payload = {
            "name":self.mqtt_config.hass_name_prefix + dict['topic'],
            "state_topic":state_topic,
            "unique_id":object_id,
            "object_id":object_id,
            "device":{
                "identifiers":[self.mqtt_config.hass_device_id],
                "name":self.mqtt_config.hass_device_name,
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

        # special handling depending on dict['comp']
        if dict['comp'] == "number":
            payload['command_topic'] = state_topic + "/on"
            #payload['mode'] = "box"
            #payload['icon'] = "mdi:lightning-bolt-outline"
            if 'min' in dict and dict['min']: payload['min'] = dict['min']
            if 'max' in dict and dict['max']: payload['max'] = dict['max']
        elif dict['comp'] == "switch":
            payload['command_topic'] = state_topic + "/on"
            payload['payload_off'] = "0"
            payload['payload_on'] = "1"

        # special handling depending on dict['class']
        if dict['class'] == "_energy_increasing":
            payload['device_class'] = "energy"
            payload['state_class'] = "total_increasing"
        elif dict['class'] == "_datetime":
            #payload['device_class'] = "date" # do not set date class, as output cuts time
            payload['value_template'] = "{{ as_datetime(value) }}"
            payload['icon'] = "mdi:calendar-arrow-right"
        elif dict['class']:
            payload['device_class'] = dict['class']
        
        self._publish(self.client, topic, json.dumps(payload), self.qos, self.retain)


    def clear_all_topics(self):
        """Clear all MQTT topics"""
        _LOGGER.debug("Start clear_all_topics")

        self._check_mqtt_connected()

        # do not use self._get_topic_base() here, as we really want to remove the HomA and "normal" topics
        homa_base = "/devices/" + self.mqtt_config.homa_systemid + "/" # e.g. "/devices/123456-solar/"
        topic_base = self.mqtt_config.topic_prefix # e.g. "aps/"

        self._publish(self.client, homa_base + "meta/name", None, self.qos, self.retain)
        self._publish(self.client, homa_base + "meta/room", None, self.qos, self.retain)

        homa_base += "controls/" # e.g. "/devices/123456-solar/controls/"
        for key, dict in _mqtt_d.items():
            self._publish(self.client, topic_base + dict['topic'], None, self.qos, self.retain)
            self._publish(self.client, homa_base + dict['topic'], None, self.qos, self.retain)
            self._publish(self.client, homa_base + dict['topic'] + "/meta/type", None, self.qos, self.retain)
            self._publish(self.client, homa_base + dict['topic'] + "/meta/order", None, self.qos, self.retain)
            self._publish(self.client, homa_base + dict['topic'] + "/meta/room", None, self.qos, self.retain)
            self._publish(self.client, homa_base + dict['topic'] + "/meta/unit", None, self.qos, self.retain)

            # clear Home Assistant config topics
            object_id = self.mqtt_config.hass_device_id + "-" + dict['topic'].replace(" ", "-")
            hass_topic = "homeassistant/sensor/" + object_id + "/config"
            if dict['class'] is None:
                break
            elif dict['class'] == "number":
                hass_topic = "homeassistant/number/" + object_id + "/config"
            elif dict['class'] == "switch":
                hass_topic = "homeassistant/switch/" + object_id + "/config"
            self._publish(self.client, hass_topic, None, self.qos, self.retain)
        
        _LOGGER.info("All MQTT topics cleared.")
