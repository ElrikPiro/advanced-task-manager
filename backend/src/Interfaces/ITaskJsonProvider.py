# class interface

from abc import ABC, abstractmethod

VALID_PROJECT_STATUS = [
    "open",
    "closed",
    "on-hold",
]


class ITaskJsonProvider(ABC):

    @abstractmethod
    def getJson(self) -> dict:
        """
        Gets the tasks json.

        Returns:
            dict: The tasks json.
        """
        pass

    @abstractmethod
    def saveJson(self, json: dict):
        pass
