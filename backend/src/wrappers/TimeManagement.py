"""
This module contains the TimeAmount and TimePoint classes, which are wrappers 
for time amounts and time points, respectively.
"""

import datetime
from math import ceil


class TimeAmount:
    """
    This module contains the TimeAmount class, which is a wrapper for time amounts.
    It allows for easy manipulation of time amounts in a human-readable format.
    """

    def __init__(self, str_representation: str):
        self.int_representation = _convert_time_string_to_miliseconds(str_representation)

    def __add__(self, other):
        return TimeAmount(str(self.int_representation + other.int_representation))

    def __sub__(self, other):
        return TimeAmount(str(self.int_representation - other.int_representation))

    def __mul__(self, other):
        return TimeAmount(str(self.int_representation * other.int_representation))

    def __truediv__(self, other):
        return TimeAmount(str(self.int_representation / other.int_representation))

    def __str__(self):
        return _convert_seconds_to_time_string(self.int_representation)
    
    def as_pomodoros(self) -> int:
        """
        Returns the time amount as a number of pomodoros.
        """
        return ceil((self.int_representation*5) / (25*60*1000))/5

class TimePoint:
    """
    This module contains the TimePoint class, which is a wrapper for time points.
    It allows for easy manipulation of time points in a human-readable format.
    """

    def __init__(self, datetime_representation: datetime.datetime):
        self.datetime_representation = datetime_representation

    def __add__(self, other : TimeAmount):
        return TimePoint(datetime.datetime.fromtimestamp(self.datetime_representation.timestamp() + other.int_representation/1000))
    
    def __str__(self):
        fullFormat = self.datetime_representation.strftime("%Y-%m-%d %H:%M:%S")
        shortFormat = self.datetime_representation.strftime("%Y-%m-%d")
        return fullFormat if self.datetime_representation.hour > 0 else shortFormat
    
    @staticmethod
    def now():
        return TimePoint(datetime.datetime.now())
    
    @staticmethod
    def today():
        return TimePoint(datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    
    @staticmethod
    def tomorrow():
        return TimePoint(datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1))
    
    @staticmethod
    def from_string(string: str):
        return TimePoint(datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M"))
    
    @staticmethod
    def from_timestamp(timestamp: int):
        return TimePoint(datetime.datetime.fromtimestamp(timestamp / 1000))



# Private helper functions in module

def _convert_time_string_to_miliseconds(value: str) -> int:
    value = str(value)
    
    sign = 0
    if value.startswith("-"):
        sign = -1
    elif value.startswith("+"):
        sign = 1
    else:
        sign = 1
        value = "+" + value

    modifier = 1000
    if value.endswith("d"):
        modifier *= 24 * 60 * 60
    elif value.endswith("h"):
        modifier *= 60 * 60
    elif value.endswith("m"):
        modifier *= 60
    elif value.endswith("w"):
        modifier *= 7 * 24 * 60 * 60
    elif value.endswith("p"):
        modifier *= 25 * 60
    else: # no letter at the end, assume pomodoros
        value += "p"
        modifier *= 25 * 60

    floatValue = float(value[1:-1])
    return int(sign * floatValue * modifier)

def _convert_seconds_to_time_string(miliseconds: int) -> str:
    pomodoros = ceil((5*miliseconds) / (25*60*1000))/5
    #round pomodoros to 1 decimal place
    days, miliseconds = divmod(miliseconds, 86400000)
    hours, miliseconds = divmod(miliseconds, 3600000)
    minutes, miliseconds = divmod(miliseconds, 60000)
    # a value only appears if it is not zero
    retval = f"{days}d" * bool(days) + f"{hours}h" * bool(hours) + f"{minutes}m" * bool(minutes) + f"{miliseconds/1000}s" * bool(miliseconds)
    return retval + f" ({pomodoros} pomodoros)" if pomodoros > 0 else "None"
    
