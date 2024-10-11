from abc import ABC, abstractmethod
from enum import Enum
import json
import os

# Enumeration of files that can be read
class FileRegistry(Enum):
    STANDALONE_TASKS_JSON = 1
    STATISTICS_JSON = 2
    OBSIDIAN_TASKS_JSON = 3

class VaultRegistry(Enum):
    OBSIDIAN = 1

class IFileBroker(ABC):

    @abstractmethod
    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        pass

    @abstractmethod
    def readFileContentJson(self, fileRegistry: FileRegistry) -> dict:
        pass

    @abstractmethod
    def writeFileContent(self, fileRegistry: FileRegistry, content: str) -> None:
        pass

    @abstractmethod
    def writeFileContentJson(self, fileRegistry: FileRegistry, content: dict) -> None:
        pass

    @abstractmethod
    def getVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str) -> list[str]:
        pass

    @abstractmethod
    def writeVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str, lines: list[str]) -> None:
        pass


# future file: FileBroker.py

class FileBroker(IFileBroker):
    def __init__(self, jsonPath : str, appdata: str, vaultPath: str):
        self.filePaths : dict[FileRegistry, str] = {
            FileRegistry.TASKS_JSON: os.path.join(jsonPath, "tasks.json"),
            FileRegistry.STATISTICS_JSON: os.path.join(jsonPath, "statistics.json"),
            FileRegistry.OBSIDIAN_TASKS_JSON: os.path.join(appdata, "obsidian", "tareas.json")
        }

        self.vaultPaths : dict[VaultRegistry, str] = {
            VaultRegistry.OBSIDIAN: vaultPath
        }

    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        with open(self.filePaths[fileRegistry], "r") as file:
            return file.read()

    def writeFileContent(self, fileRegistry: FileRegistry, content: str) -> None:
        with open(self.filePaths[fileRegistry], "w") as file:
            file.write(content)

    def readFileContentJson(self, fileRegistry: FileRegistry) -> dict:
        with open(self.filePaths[fileRegistry], "r") as file:
            return json.load(file)
        
    def writeFileContentJson(self, fileRegistry: FileRegistry, content: dict) -> None:
        with open(self.filePaths[fileRegistry], "w") as file:
            json.dump(content, file, indent=4)

    def getVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str) -> list[str]:
        with open(os.path.join(self.vaultPaths[vaultRegistry], relativePath), "r") as file:
            return file.readlines()
        
    def writeVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str, lines: list[str]) -> None:
        with open(os.path.join(self.vaultPaths[vaultRegistry], relativePath), "w") as file:
            file.writelines(lines)