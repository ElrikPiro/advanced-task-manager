import json
import os
from .Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry

class FileBroker(IFileBroker):
    def __init__(self, jsonPath : str, appdata: str, vaultPath: str):
        defaultTaskJson = '{"tasks": [], "pomodoros_per_day": "2"}'

        self.filePaths : dict[FileRegistry, dict] = {
            FileRegistry.STANDALONE_TASKS_JSON: {"path": os.path.join(jsonPath, "tasks.json"), "default": defaultTaskJson},
            FileRegistry.STATISTICS_JSON: {"path": os.path.join(jsonPath, "statistics.json"), "default": '{}'},
            FileRegistry.OBSIDIAN_TASKS_JSON: {"path": os.path.join(appdata, "obsidian", "tareas.json"), "default": defaultTaskJson},
            FileRegistry.OBSIDIAN_TASKS_MD: {"path": os.path.join(vaultPath, "ObsidianTaskProvider.md"), "default": f"# Task list{os.linesep}{os.linesep}"}, #TODO: this file must be defined as a configuration variable
            FileRegistry.LAST_RECEIVED_FILE: {"path": os.path.join(jsonPath, "import.dat"), "default": defaultTaskJson},
        }

        self.vaultPaths : dict[VaultRegistry, str] = {
            VaultRegistry.OBSIDIAN: vaultPath
        }

    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        try:
            with open(self.filePaths[fileRegistry]["path"], "r") as file:
                return file.read()
        except FileNotFoundError:
            print(f"File not found: {self.filePaths[fileRegistry]['path']}")
            return self.filePaths[fileRegistry]["default"]

    def writeFileContent(self, fileRegistry: FileRegistry, content: str) -> None:
        with open(self.filePaths[fileRegistry]["path"], 'w+') as file:
            file.write(content)

    def readFileContentJson(self, fileRegistry: FileRegistry) -> dict:
        try:
            with open(self.filePaths[fileRegistry]["path"], "r") as file:
                return json.load(file)
        except FileNotFoundError:
            print(f"File not found: {self.filePaths[fileRegistry]['path']}")
            return json.loads(self.filePaths[fileRegistry]["default"])
        
    def writeFileContentJson(self, fileRegistry: FileRegistry, content: dict) -> None:
        with open(self.filePaths[fileRegistry]["path"], 'w+') as file:
            json.dump(content, file, indent=4)

    def getVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str) -> list[str]:
        with open(os.path.join(self.vaultPaths[vaultRegistry], relativePath), "r") as file:
            return file.readlines()
        
    def writeVaultFileLines(self, vaultRegistry: VaultRegistry, relativePath: str, lines: list[str]) -> None:
        with open(os.path.join(self.vaultPaths[vaultRegistry], relativePath), "w") as file:
            file.writelines(lines)