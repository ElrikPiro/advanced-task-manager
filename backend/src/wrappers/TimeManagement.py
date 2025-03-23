
"""
This module contains the TimeAmount and TimePoint classes, which are wrappers
for time amounts and time points, respectively.
"""

import datetime
from math import ceil


class TimeAmount:
    """
    This module contains the TimeAmount class, which is a wrapper for
        time amounts.
    It allows for easy manipulation of time amounts in a human-readable format.
    """

    def __init__(self, str_representation: str):
        conversionFunc = _convert_time_string_to_miliseconds if str_representation.find(":") == -1 else _convert_hour_string_to_miliseconds
        self.int_representation = conversionFunc(
            str_representation
        )

    def __add__(self, other):
        result = TimeAmount("0.0p")
        result.int_representation = self.int_representation + other.int_representation
        return result

    def __sub__(self, other):
        result = TimeAmount("0.0p")
        result.int_representation = self.int_representation - other.int_representation
        return result

    def __mul__(self, other):
        result = TimeAmount("0.0p")
        result.int_representation = self.int_representation * other.int_representation
        return result

    def __truediv__(self, other):
        result = TimeAmount("0.0p")
        result.int_representation = int(self.int_representation / other.int_representation)
        return result

    def __str__(self):
        return _convert_seconds_to_time_string(self.int_representation)

    def as_pomodoros(self) -> float:
        """
        Returns the time amount as a number of pomodoros.
        """
        return ceil((self.int_representation * 5) / (25 * 60 * 1000)) / 5

    def as_days(self) -> int:
        """
        Returns the time amount as a number of days.
        """
        return int(self.int_representation / 86400000)


class TimePoint:
    """
    This module contains the TimePoint class, which is a wrapper for time points.
    It allows for easy manipulation of time points in a human-readable format.
    """

    def __init__(self, datetime_representation: datetime.datetime):
        self.datetime_representation = datetime_representation

    def __add__(self, other: TimeAmount):
        return TimePoint(datetime.datetime.fromtimestamp(self.datetime_representation.timestamp() + other.int_representation / 1000))

    def __eq__(self, other):
        return self.datetime_representation == other.datetime_representation

    def __str__(self):
        fullFormat = self.datetime_representation.strftime("%Y-%m-%dT%H:%M")
        shortFormat = self.datetime_representation.strftime("%Y-%m-%d")
        return fullFormat if self.datetime_representation.hour > 0 or self.datetime_representation.minute > 0 else shortFormat

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
        try:
            return TimePoint(datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M"))
        except ValueError:
            return TimePoint(datetime.datetime.strptime(string, "%Y-%m-%d"))

    def as_int(self):
        return int(self.datetime_representation.timestamp() * 1e3)

    def strip_time(self):
        return TimePoint(self.datetime_representation.replace(hour=0, minute=0, second=0, microsecond=0))


# Private helper functions in module


def _convert_hour_string_to_miliseconds(value: str) -> int:
    """
    Converts a string representing a time amount to miliseconds.

    This function expects an string representing an amount of time in the format HH:MM and converts it to miliseconds.

    Params:
        value: The string representing the time amount.
    Returns:
        The time amount in miliseconds.
    Throws:
        ValueError: If the time amount is not in the expected format.
    """
    value = str(value)
    hours, minutes = value.split(":")
    return int(hours) * 60 * 60 * 1000 + int(minutes) * 60 * 1000


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
    elif value.endswith("s"):
        modifier *= 1
    else:
        raise ValueError("Invalid time string format (no time unit defined)")

    floatValue = float(value[1:-1])
    return int(sign * floatValue * modifier)


def _convert_seconds_to_time_string(miliseconds: int) -> str:
    pomodoros = ceil((5 * miliseconds) / (25 * 60 * 1000)) / 5
    # round pomodoros to 1 decimal place
    days, miliseconds = divmod(miliseconds, 86400000)
    hours, miliseconds = divmod(miliseconds, 3600000)
    minutes, miliseconds = divmod(miliseconds, 60000)
    # a value only appears if it is not zero
    retval = f"{days}d" * bool(days) + f"{hours}h" * bool(hours) + f"{minutes}m" * bool(minutes) + f"{miliseconds/1000}s" * bool(miliseconds)
    return retval + f" ({pomodoros} pomodoros)" if pomodoros > 0 else "None"
