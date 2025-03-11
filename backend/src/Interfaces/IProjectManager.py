from abc import ABC, abstractmethod
from typing import List
from enum import Enum


class ProjectCommands(Enum):
    LIST = "list"
    CAT = "cat"
    EDIT = "edit"
    ADD = "add"
    REMOVE = "remove"
    OPEN = "open"
    CLOSE = "close"
    HOLD = "hold"

    @classmethod
    def values(cls) -> List[str]:
        return [cmd.value for cmd in cls]


class IProjectManager(ABC):
    """
    Interface for project management operations.
    """

    @abstractmethod
    def process_command(self, command: str, messageArgs: List[str]) -> str:
        """
        Process a command with its arguments.

        Args:
            command (str): The command to process.
            messageArgs (List[str]): Arguments for the command.
        """
        pass
