# class interface

from abc import ABC, abstractmethod
from typing import Callable
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

    def updateJson(self, updater: Callable[[TaskJsonType], TaskJsonType]) -> TaskJsonType:
        """Atomically update the current document and return its committed value.

        Providers that cannot safely mutate their backing store leave this
        operation unsupported instead of emulating it with a stale snapshot.
        """
        raise NotImplementedError("This task JSON provider does not support atomic updates")

    def parseTaskFile(self, relative_path: str, lines: list[str]) -> list[dict[str, str]]:
        """Parse task rows from supplied content without reading or writing files."""
        raise NotImplementedError("This task JSON provider cannot parse standalone Markdown files")
