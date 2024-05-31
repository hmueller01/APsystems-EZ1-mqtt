# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Handle APsystemsEZ1M ECU requests"""
import logging

from APsystemsEZ1 import APsystemsEZ1M, ReturnDeviceInfo, ReturnOutputData
from astral import LocationInfo
from astral.sun import daylight
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)


class ECU:
    def __init__(self, ecu_config):
        self.inverter = APsystemsEZ1M(ecu_config.ipaddr, ecu_config.port)
        self.stop_at_night = ecu_config.stop_at_night
        if self.stop_at_night:
            self.city = LocationInfo("", "", 
                                     ecu_config.timezone, 
                                     ecu_config.ecu_position_latitude,
                                     ecu_config.ecu_position_longitude)


    def night(self):
        night_end, night_start = daylight(self.city.observer, tzinfo=self.city.tzinfo)
        night_end += timedelta(days=1)
        return night_start, night_end
    
    
    def is_night(self, time: datetime = None):
        if time is None: time = datetime.now()
        night_start, night_end = self.night()
        _LOGGER.debug(f'Night start: {night_start}')
        _LOGGER.debug(f'Night end  : {night_end}')
        return (self.stop_at_night and 
                night_start < time.astimezone(self.city.tzinfo) < night_end)


    def wake_up_time(self):
        night_start, night_end = self.night()
        return night_end


    async def update_data(self) -> ReturnOutputData | None:
        _LOGGER.debug("Start ECU update data")
        data = None

        try:
            # Get output data
            data = await self.inverter.get_output_data()
            _LOGGER.debug(f"Output Data: {data}")
        except Exception as e:
            # Handle any exceptions that occur during the data fetch and print the error.
            _LOGGER.warning("An exception occured: %s -> %s", e.__class__.__name__, str(e))
        return data


    async def update_info(self) -> ReturnDeviceInfo | None:
        _LOGGER.debug("Start ECU update info")
        info = None

        try:
            # Get output data
            info = await self.inverter.get_device_info()
            _LOGGER.debug(f"Output Info: {info}")
        except Exception as e:
            # Handle any exceptions that occur during the data fetch and print the error.
            _LOGGER.warning("An exception occured: %s -> %s", e.__class__.__name__, str(e))
        return info
