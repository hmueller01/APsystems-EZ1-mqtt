# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

# pylint: disable=too-many-instance-attributes, too-few-public-methods

"""Application config classes, can be set by file or env variable"""
import os
import yaml

from str2bool import str2bool_exc

class MQTTConfig:
    """MQTT config"""

    def __init__(self, cfg):
        self.broker_addr: str = cfg.get("MQTT_BROKER_HOST", "127.0.0.1")
        self.broker_port: int = int(cfg.get("MQTT_BROKER_PORT", 1883))
        self.broker_user: str = cfg.get("MQTT_BROKER_USER", "")
        self.broker_passwd: str = cfg.get("MQTT_BROKER_PASSWD", "")
        self.client_id: str = cfg.get("MQTT_CLIENT_ID", "")
        self.topic_prefix: str = cfg.get("MQTT_TOPIC_PREFIX", "")
        self.secured_connection = str2bool_exc(str(
            cfg.get("MQTT_BROKER_SECURED_CONNECTION", "f")))
        if self.secured_connection:
            self.cacerts_path = cfg.get("MQTT_BROKER_CACERTS_PATH", None)

        self.homa_enabled = str2bool_exc(str(cfg.get("HOMA_ENABLED", "f")))
        self.homa_systemid: str = cfg.get("HOMA_SYSTEMID", "")
        self.homa_room: str = cfg.get("HOMA_ROOM", "Sensors")
        self.homa_name: str = cfg.get("HOMA_NAME", "Solar PV")

        self.hass_enabled = str2bool_exc(str(cfg.get("HASS_ENABLED", "f")))
        self.hass_device_id: str = cfg.get("HASS_DEVICE_ID", "")
        self.hass_device_name: str = cfg.get("HASS_DEVICE_NAME", "Solar PV")
        self.hass_name_prefix: str = cfg.get("HASS_NAME_PREFIX", "")
        self.hass_area: str = cfg.get("HASS_AREA", "Energie")


class ECUConfig:
    """ECU config"""

    def __init__(self, cfg):
        self.ipaddr = cfg.get("APS_ECU_IP", "")
        self.port = int(cfg.get("APS_ECU_PORT", 8050))
        self.update_interval = int(cfg.get("APS_ECU_UPDATE_INTERVAL", 15))
        self.timezone = cfg.get("APS_ECU_TIMEZONE", os.getenv("TZ", None))
        self.stop_at_night = str2bool_exc(str(cfg.get("APS_ECU_STOP_AT_NIGHT", "f")))
        if self.stop_at_night:
            self.ecu_position_latitude = float(cfg.get("APS_ECU_POSITION_LAT", 52.5162))
            self.ecu_position_longitude = float(cfg.get("APS_ECU_POSITION_LNG", 13.3777))


class Config:
    """Application config"""

    def __init__(self, config_path=None):
        if config_path is not None:
            self.__load_yaml_config_file(config_path)
        elif os.getenv("CONFIG_FILE") is not None:
            self.__load_yaml_config_file(os.getenv("CONFIG_FILE"))
        else:
            cfg = os.environ
            self.mqtt_config = MQTTConfig(cfg)
            self.ecu_config = ECUConfig(cfg)


    def __load_yaml_config_file(self, config_path):
        with open(config_path, "r", encoding="UTF-8") as yml_cfg:
            cfg = yaml.safe_load(yml_cfg)
            self.mqtt_config = MQTTConfig(cfg["mqtt"])
            self.ecu_config = ECUConfig(cfg["ecu"])
