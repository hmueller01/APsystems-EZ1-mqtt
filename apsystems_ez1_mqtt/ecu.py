# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Handle APsystemsEZ1M ECU requests"""
import logging

from datetime import datetime, timedelta

from APsystemsEZ1 import APsystemsEZ1M
from astral import LocationInfo
from astral.sun import daylight
from apsystems_ez1_mqtt.config import ECUConfig

_LOGGER = logging.getLogger(__name__)


class ECU(APsystemsEZ1M):
    """
    Extend class APsystemsEZ1M by night information and boolean OnOff power status
    """

    def __init__(self, ecu_config: ECUConfig, timeout: int = None):
        min_timeout: int = 2
        if not timeout:
            timeout = 10 if ecu_config.update_interval > 10 else ecu_config.update_interval
        if timeout <= min_timeout:
            raise ValueError(f"timeout {timeout} too low, must be > {min_timeout}")
        super().__init__(ecu_config.ipaddr, ecu_config.port, timeout)
        self.stop_at_night = ecu_config.stop_at_night
        if self.stop_at_night:
            self.city = LocationInfo("", "",
                                     ecu_config.timezone,
                                     ecu_config.ecu_position_latitude,
                                     ecu_config.ecu_position_longitude)


    def night(self):
        """Get start and end time of night depending on location and time zone"""
        night_end, night_start = daylight(self.city.observer, tzinfo=self.city.tzinfo)
        night_end += timedelta(days=1)
        return night_start, night_end


    def is_night(self, time: datetime = None):
        """Check it time is in night"""
        if time is None: time = datetime.now()
        night_start, night_end = self.night()
        _LOGGER.debug('Night start: %s', night_start.isoformat())
        _LOGGER.debug('Night end  : %s', night_end.isoformat())
        return (self.stop_at_night and
                night_start < time.astimezone(self.city.tzinfo) < night_end)


    def wake_up_time(self):
        """Get wake up time (end of night)"""
        _, night_end = self.night()
        return night_end
