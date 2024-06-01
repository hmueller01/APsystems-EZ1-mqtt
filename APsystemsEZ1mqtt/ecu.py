# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Handle APsystemsEZ1M ECU requests"""
import logging

from APsystemsEZ1 import APsystemsEZ1M
from astral import LocationInfo
from astral.sun import daylight
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)


class ECU(APsystemsEZ1M):
    def __init__(self, ecu_config, timeout: int = 10):
        super().__init__(ecu_config.ipaddr, ecu_config.port, timeout)
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
