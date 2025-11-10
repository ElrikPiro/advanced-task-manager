from abc import ABC, abstractmethod
from enum import Enum
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
    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        pass

    @abstractmethod
    def readFileContentJson(self, fileRegistry: FileRegistry) -> FileContentJson:
        pass

    @abstractmethod
    def readStatisticsFileContentJson(self) -> StatisticsFileContentJson:
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
    def getVaultFiles(self, vaultRegistry: VaultRegistry) -> list[tuple[str, float]]:
        pass
