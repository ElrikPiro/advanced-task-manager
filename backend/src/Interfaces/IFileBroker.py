from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable
from ..Utils import FileContentJson, FileContentString, StatisticsFileContentJson


# Enumeration of files that can be read
class FileRegistry(Enum):
    STANDALONE_TASKS_JSON = 1
    STATISTICS_JSON = 2
    OBSIDIAN_TASKS_JSON = 3
    OBSIDIAN_TASKS_MD = 4
    LAST_RECEIVED_FILE = 5


class VaultRegistry(Enum):
    OBSIDIAN = 1


class IFileBroker(ABC):

    @abstractmethod
    def getFilePath(self, fileRegistry: FileRegistry) -> str:
        """Return the configured path for a registered file."""
        pass

    @abstractmethod
    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        pass

    @abstractmethod
    def readFileContentJson(self, fileRegistry: FileRegistry) -> FileContentJson:
        pass

    @abstractmethod
    def readStatisticsFileContentJson(self) -> StatisticsFileContentJson:
        pass

    @abstractmethod
    def updateFileContent(self, fileRegistry: FileRegistry, updater: Callable[[str], str]) -> str:
        """Update latest text and return saved text; updater must be side-effect free."""
        pass

    @abstractmethod
    def updateFileContentJson(
        self,
        fileRegistry: FileRegistry,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Update latest JSON and return saved data; updater must be side-effect free."""
        pass

    @abstractmethod
    def initializeFileContent(self, fileRegistry: FileRegistry) -> None:
        """Create a registered file with its default content if it is absent.

        Reads must remain non-mutating; callers that own startup initialization
        can use this method to materialize a default explicitly.
        """
        pass

    @abstractmethod
    def writeFileContent(self, fileRegistry: FileRegistry, content: FileContentString) -> None:
        pass

    @abstractmethod
    def writeFileContentJson(self, fileRegistry: FileRegistry, content: FileContentJson | StatisticsFileContentJson) -> None:
        pass

    @abstractmethod
    def getVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str) -> list[str]:
        pass

    @abstractmethod
    def writeVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str, lines: list[str]) -> None:
        pass

    @abstractmethod
    def updateVaultFileLines(
        self,
        vaultRegistry: VaultRegistry,
        relativePath: str,
        updater: Callable[[list[str]], list[str]],
    ) -> list[str]:
        """Update latest lines and return saved lines; updater must be side-effect free."""
        pass

    @abstractmethod
    def createVaultFileLinesIfAbsent(
        self,
        vaultRegistry: VaultRegistry,
        relativePath: str,
        lines: list[str],
    ) -> bool:
        """Create a vault file without replacing an existing note."""
        pass

    @abstractmethod
    def getVaultFiles(self, vaultRegistry: VaultRegistry) -> list[tuple[str, float]]:
        pass
