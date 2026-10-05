from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, List, Mapping

from src.domain.models import ProjectMutationResult


class ProjectCommands(Enum):
    LIST = "list"
    CAT = "cat"
    EDIT = "edit"
    ADD = "add"
    REMOVE = "remove"
    OPEN = "open"
    CLOSE = "close"
    HOLD = "hold"
    HELP = "help"

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

    @abstractmethod
    def perform_operation(
        self,
        operation_type: str,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> ProjectMutationResult:
        """Apply a typed project change and return project data, not display text."""
        pass

    @abstractmethod
    def validate_operation_structure(
        self,
        operation_type: str,
        project_name: str,
        parameters: Mapping[str, Any],
    ) -> None:
        """Validate a project's operation fields without reading stored data."""
        pass
