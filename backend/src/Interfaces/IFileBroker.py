from abc import ABC, abstractmethod
from enum import Enum
import json
import os

# Enumeration of files that can be read
class FileRegistry(Enum):
    STANDALONE_TASKS_JSON = 1
    STATISTICS_JSON = 2
    OBSIDIAN_TASKS_JSON = 3

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

# future file: FileBroker.py

class FileBroker(IFileBroker):
    def __init__(self, dataStorePath: str, jsonPath : str, appdata: str):
        self.filePaths : dict[FileRegistry, str] = {
            FileRegistry.TASKS_JSON: os.path.join(dataStorePath, "tasks.json"),
            FileRegistry.STATISTICS_JSON: jsonPath,
            FileRegistry.OBSIDIAN_TASKS_JSON: os.path.join(appdata, "obsidian", "tareas.json")
        }

    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        with open(self.filePaths[fileRegistry], "r") as file:
            return file.read()

    def writeFileContent(self, fileRegistry: FileRegistry, content: str) -> None:
        with open(self.filePaths[fileRegistry], "w") as file:
            file.write(content)

    @abstractmethod
    def readFileContentJson(self, fileRegistry: FileRegistry) -> dict:
        with open(self.filePaths[fileRegistry], "r") as file:
            return json.load(file)
        
    @abstractmethod
    def writeFileContentJson(self, fileRegistry: FileRegistry, content: dict) -> None:
        with open(self.filePaths[fileRegistry], "w") as file:
            json.dump(content, file, indent=4)