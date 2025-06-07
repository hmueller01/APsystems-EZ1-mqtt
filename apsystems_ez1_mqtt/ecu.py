# Author: Holger Mueller <github euhm.de>
# Based on aps2mqtt by Florian L., https://github.com/fligneul/aps2mqtt

"""Handle APsystemsEZ1M ECU requests"""
import logging

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from APsystemsEZ1 import APsystemsEZ1M
from astral import LocationInfo
from astral.sun import daylight
from apsystems_ez1_mqtt.config import ECUConfig

_LOGGER = logging.getLogger(__name__)

@dataclass
class OutputData():  # pylint: disable=too-many-instance-attributes
    """Extended ReturnOutputData data class to include daily energy consumption."""
    p1: float # power output reading of inverter input 1
    e1: float # energy reading for inverter input 1 (since last reset)
    te1: float # total energy for inverter input 1
    d1: float # daily energy for inverter input 1
    p2: float # power output reading of inverter input 2
    e2: float # energy reading for inverter input 2 (since last reset)
    te2: float # total energy for inverter input 2
    d2: float # daily energy for inverter input 2


class ECU(APsystemsEZ1M):
    """Extend class APsystemsEZ1M by night information and boolean OnOff power status."""

    def __init__(self, ecu_config: ECUConfig, timeout: Optional[int] = None):
        min_timeout: int = 2
        if not timeout:
            timeout = 10 if ecu_config.update_interval > 10 else ecu_config.update_interval
        if timeout <= min_timeout:
            raise ValueError(f"timeout {timeout} too low, must be > {min_timeout}")
        super().__init__(ecu_config.ipaddr, ecu_config.port, timeout, enable_debounce=True)
        self.stop_at_night = ecu_config.stop_at_night
        self.city = LocationInfo("", "",
                                    ecu_config.timezone,
                                    ecu_config.ecu_position_latitude,
                                    ecu_config.ecu_position_longitude)
        self.day_start_date = None
        self.te1_day_start = 0.0
        self.te2_day_start = 0.0


    def night(self):
        """Get start and end time of night depending on location and time zone"""
        night_end, night_start = daylight(self.city.observer, tzinfo=self.city.tzinfo)
        night_end += timedelta(days=1)
        return night_start, night_end


    def is_night(self, time: Optional[datetime] = None):
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


    async def get_output_data_ext(self) -> OutputData | None:
        """
        Retrieves the output data from the device and calculates daily energy consumption.
        This method extends the functionality of the base class to include daily energy
        calculations for both inverter inputs.

        The returned data includes various parameters such as power output status ('p1', 'p2'),
        energy readings ('e1', 'e2'), energy readings ('d1', 'd2') and total energy ('te1', 'te2')
        for two different inputs of the inverter.

        :return: Information about energy/power-related information
        """
        ecu_data = await super().get_output_data()
        if ecu_data is None:
            return None

        # Check if we are at the start of a new day
        now = datetime.now(self.city.tzinfo)
        if now.date() != self.day_start_date:
            self.day_start_date = now.date()
            # Reset daily energy for inverter inputs
            self.te1_day_start = ecu_data.te1
            self.te2_day_start = ecu_data.te2

        return OutputData(
            p1=ecu_data.p1,
            e1=ecu_data.e1,
            te1=ecu_data.te1,
            d1=ecu_data.te1 - self.te1_day_start,
            p2=ecu_data.p2,
            e2=ecu_data.e2,
            te2=ecu_data.te2,
            d2=ecu_data.te2 - self.te2_day_start
        )
