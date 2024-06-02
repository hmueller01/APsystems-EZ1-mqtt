# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Query APsystems EZ1 inverter data periodically and send them to the MQTT broker"""
import asyncio
import logging
import sys
import time

from APsystemsEZ1 import ReturnDeviceInfo
from APsystemsEZ1mqtt.config import Config
from APsystemsEZ1mqtt.ecu import ECU
from APsystemsEZ1mqtt.mqtthandler import MQTTHandler
from argparse import ArgumentParser
from datetime import datetime, timedelta

_ecu: ECU
_LOGGER = logging.getLogger(__name__)
_mqtt: MQTTHandler


def cli_args():
    """Get command line arguments and parse them"""
    parser = ArgumentParser(prog="APsystemsEZ1mqtt", 
                            description="Read data from APsystems EZ1 local API and send to MQTT broker, configure HomA and Home Assistant environment.")
    parser.add_argument("-c", "--config", dest="config_path", help="load YAML config file", metavar="FILE")
    parser.add_argument("-d", "--debug", dest="debug", help="enable debug logs", action="store_true")
    parser.add_argument("-r", "--remove", dest="remove", help="remove retained MQTT topics", action="store_true")
    return parser.parse_args()


async def async_on_status_power(status: bool):
    """Async callback function for MQTTHandler on_status_power"""
    global _ecu, _mqtt
    _LOGGER.debug(f"Start async_on_status_power({status})")
    status_power = await _ecu.set_status_power(status)
    _mqtt.publish_status_power(status_power)


async def main():
    """Main application. Does not return. Terminate using <Ctrl>-C."""
    global _ecu, _LOGGER, _mqtt
    args = cli_args()
    conf = Config(args.config_path)
    if not conf.ecu_config.ipaddr:
        _LOGGER.error("APS_ECU_IP not found. No config given? Use -h")
        sys.exit(1)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(levelname)s:%(name)s.%(funcName)s(): %(message)s")
    _ecu = ECU(conf.ecu_config)

    while (ecu_info := await _ecu.get_device_info()) is None:
        if args.debug:
            _LOGGER.info("Can't read APsystems info data. Setting dummy data.")
            ecu_info = ReturnDeviceInfo(
                deviceId='debug dummy Id',
                devVer='debug dummy Ver',
                ssid='debug dummy ssid',
                ipAddr='192.168.9.9',
                minPower=int(30),
                maxPower=int(800))
            break
        else:
            _LOGGER.error("Can't read APsystems info data. Waiting for a minute ...")
            time.sleep(60)

    if not conf.mqtt_config.homa_systemid:
        # if no homa_systemid is given in config use deviceId
        conf.mqtt_config.homa_systemid = ecu_info.deviceId
    if not conf.mqtt_config.hass_device_id:
        # if no hass_device_id is given in config use deviceId
        conf.mqtt_config.hass_device_id = ecu_info.deviceId
    _mqtt = MQTTHandler(asyncio.get_event_loop(), async_on_status_power, conf.mqtt_config, retain = not args.debug)
    _mqtt.connect_mqtt()
    
    # if -r is passed remove all retained topics and exit
    if args.remove:
        _mqtt.clear_all_topics()
        sys.exit(0)

    _mqtt.hass_init(conf.ecu_config, ecu_info) # must init before homa_init
    _mqtt.homa_init(ecu_info, _ecu.city.tzinfo)

    # do this only once a day
    max_power = await _ecu.get_max_power()
    status_power = await _ecu.get_status_power()
    _mqtt.publish_max_power(max_power)
    _mqtt.publish_status_power(status_power)

    while True:
        now = datetime.now()
        if _ecu.is_night(now):
            sleeptime = _ecu.wake_up_time().timestamp() - now.timestamp()
        else:
            sleeptime = float(conf.ecu_config.update_interval)
            try:
                ecu_data = await _ecu.get_output_data()
                if ecu_data is not None:
                    _mqtt.publish_data(ecu_data)
            except Exception as e:
                _LOGGER.error("An exception occured: %s -> %s", e.__class__.__name__, str(e))

        _LOGGER.info("Next update at: %s", (now.astimezone(_ecu.city.tzinfo) + timedelta(0, sleeptime)).strftime("%Y-%m-%d %H:%M:%S %Z"))
        # compensate code runtime
        sleeptime = max(0, sleeptime - (datetime.now().timestamp() - now.timestamp()))
        _LOGGER.debug(f"Time to sleep: {sleeptime:0.2f}s")
        time.sleep(sleeptime)
        #await asyncio.sleep(sleeptime)


if __name__ == "__main__":
    # Run the main coroutine.
    # This is the entry point of the script and it runs the main function in an asynchronous manner.
    asyncio.run(main())
