# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Query APsystems EZ1 inverter data periodically and send them to the MQTT broker"""
import asyncio
import logging
import sys

from argparse import ArgumentParser
from datetime import datetime, timedelta

from aiohttp.http_exceptions import HttpBadRequest
from APsystemsEZ1 import ReturnDeviceInfo, InverterReturnedError
from apsystems_ez1_mqtt.config import Config
from apsystems_ez1_mqtt.ecu import ECU
from apsystems_ez1_mqtt.mqtthandler import MQTTHandler

_ecu: ECU
_logger = logging.getLogger(__name__)
_loop: asyncio.AbstractEventLoop
_mqtt: MQTTHandler


def cli_args():
    """Get command line arguments and parse them"""
    parser = ArgumentParser(prog="APsystemsEZ1mqtt",
                            description="Read data from APsystems EZ1 local API and send to MQTT "
                                        "broker, configure HomA and Home Assistant environment.")
    parser.add_argument("-c", "--config", dest="config_path", help="load YAML config file", metavar="FILE")
    parser.add_argument("-d", "--debug", dest="debug", help="enable debug logs", action="store_true")
    parser.add_argument("-r", "--remove", dest="remove", help="remove retained MQTT topics", action="store_true")
    return parser.parse_args()


async def async_on_status_power(status: bool):
    """Async callback function for MQTTHandler on_status_power"""
    _logger.debug("Start async_on_status_power(status=%r)", status)
    status_power = await _ecu.set_status_power(status)
    _mqtt.publish_status_power(status_power)


async def async_on_max_power(value: int):
    """Async callback function for MQTTHandler on_max_power"""
    _logger.debug("Start async_on_max_power(value=%d)", value)
    max_power = await _ecu.set_max_power(value)
    _mqtt.publish_max_power(max_power)


async def periodic_wakeup():
    """Periodic wakeup is needed to let new tasks from other threads be executed"""
    while True:
        await asyncio.sleep(1)


async def periodic_get_data(interval: float):
    """Periodic get output data from ecu"""
    while True:
        now = datetime.now()
        _logger.debug("Start periodic_get_data: %s", now.isoformat())
        if _ecu.is_night(now):
            sleeptime = _ecu.wake_up_time().timestamp() - now.timestamp()
        else:
            sleeptime = interval
            try:
                ecu_data = await _ecu.get_output_data()
                _mqtt.publish_data(ecu_data)
            except (InverterReturnedError, HttpBadRequest) as e:
                _logger.error("An exception occured: %s -> %s", e.__class__.__name__, str(e))

        next_update_time = (now.astimezone(_ecu.city.tzinfo) + timedelta(0, sleeptime)).strftime("%Y-%m-%d %H:%M:%S %Z")
        # compensate code runtime
        sleeptime = max(0, sleeptime - (datetime.now().timestamp() - now.timestamp()))
        _logger.debug("Next update at: %s (in %0.2fs)", next_update_time, sleeptime)
        await asyncio.sleep(sleeptime)


async def periodic_get_power(interval: float):
    """Periodic get power status from ecu"""
    while True:
        now = datetime.now()
        _logger.debug("Start periodic_get_power: %s", now.isoformat())
        if _ecu.is_night(now):
            sleeptime = _ecu.wake_up_time().timestamp() - now.timestamp() + interval
        else:
            sleeptime = interval
            try:
                max_power = await _ecu.get_max_power()
                _mqtt.publish_max_power(max_power)
                status_power = await _ecu.get_status_power()
                _mqtt.publish_status_power(status_power)
            except (InverterReturnedError, HttpBadRequest) as e:
                _logger.error("An exception occured: %s -> %s", e.__class__.__name__, str(e))

        next_update_time = (now.astimezone(_ecu.city.tzinfo) + timedelta(0, sleeptime)).strftime("%Y-%m-%d %H:%M:%S %Z")
        _logger.debug("Next update at: %s (in %0.2fs)", next_update_time, sleeptime)
        await asyncio.sleep(sleeptime)


async def main():
    """Main application. Does not return. Terminate using <Ctrl>-C."""
    global _ecu, _mqtt, _loop  # pylint: disable=global-statement

    _loop = asyncio.get_event_loop()
    args = cli_args()
    conf = Config(args.config_path)
    if not conf.ecu_config.ipaddr:
        _logger.error("APS_ECU_IP not found. No config given? Use -h")
        sys.exit(1)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(levelname)s:%(name)s.%(funcName)s(): %(message)s")
    _ecu = ECU(conf.ecu_config)

    _logger.info("Read data from APsystems EZ1 at http://%s:%d", conf.ecu_config.ipaddr, conf.ecu_config.port)
    ecu_info = None
    while ecu_info is None:
        try:
            ecu_info = await _ecu.get_device_info()
        except (InverterReturnedError, HttpBadRequest):
            if args.debug:
                _logger.info("Can't read APsystems info data. Setting dummy data.")
                ecu_info = ReturnDeviceInfo(
                    deviceId='123456789',
                    devVer='debug dummy Ver',
                    ssid='debug dummy ssid',
                    ipAddr='192.168.9.9',
                    minPower=int(30),
                    maxPower=int(800))
            else:
                _logger.error("Can't read APsystems info data. Waiting for a minute ...")
                await asyncio.sleep(60)

    if not conf.mqtt_config.homa_systemid:
        # if no homa_systemid is given in config use deviceId
        conf.mqtt_config.homa_systemid = ecu_info.deviceId
    if not conf.mqtt_config.hass_device_id:
        # if no hass_device_id is given in config use deviceId
        conf.mqtt_config.hass_device_id = ecu_info.deviceId
    _mqtt = MQTTHandler(lambda status: _loop.call_soon_threadsafe(asyncio.create_task, async_on_status_power(status)),
                        lambda value: _loop.call_soon_threadsafe(asyncio.create_task, async_on_max_power(value)),
                        conf.mqtt_config, retain = not args.debug)
    _mqtt.connect_mqtt()

    # if -r is passed remove all retained topics and exit
    if args.remove:
        _mqtt.clear_all_topics()
        sys.exit(0)

    _mqtt.hass_init(conf.ecu_config, ecu_info) # must init before homa_init
    _mqtt.homa_init(ecu_info, _ecu.city.tzinfo)

    _logger.info("Started all periodic tasks. Press <Ctrl>-C to terminate.")
    await asyncio.gather(
        periodic_wakeup(),
        periodic_get_data(conf.ecu_config.update_interval),
        periodic_get_power(600), # 10min update interval
    )


if __name__ == "__main__":
    # This is the entry point of the script and it runs the main function in an asynchronous manner (coroutine).
    asyncio.run(main())
