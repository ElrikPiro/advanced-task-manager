# class interface

from abc import ABC, abstractmethod
from ..Utils import TaskJsonType

VALID_PROJECT_STATUS = [
    "open",
    "closed",
    "on-hold",
]


class ITaskJsonProvider(ABC):

    @abstractmethod
    def getJson(self) -> TaskJsonType:
        """
        Gets the tasks json.

        Returns:
            dict: The tasks json.
        """
        pass

    @abstractmethod
    def discover(self) -> TaskJsonType:
        """Run explicit provider reconciliation and return the resulting data.

        Unlike getJson(), this method may persist discoveries. It is intended
        for startup and maintenance hooks, never for a read-only query.
        """
        pass

    @abstractmethod
    def saveJson(self, json: TaskJsonType) -> None:
        pass
