import json
import os
import typing
from .Utils import FileContent, FileContentJson, StatisticsFileContentJson
from .Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry


class FileBroker(IFileBroker):
    def __init__(self, jsonPath: str, appdata: str, vaultPath: str):
        defaultTaskJson: FileContent = '{"tasks": []}'

        self.filePaths: dict[FileRegistry, dict[str, FileContent]] = {
            FileRegistry.STANDALONE_TASKS_JSON: {
                "path": os.path.join(jsonPath, "tasks.json"),
                "default": defaultTaskJson
            },
            FileRegistry.STATISTICS_JSON: {
                "path": os.path.join(jsonPath, "statistics.json"),
                "default": '{}'
            },
            FileRegistry.OBSIDIAN_TASKS_JSON: {
                "path": os.path.join(appdata, "obsidian", "tareas.json"),
                "default": defaultTaskJson
            },
            FileRegistry.OBSIDIAN_TASKS_MD: {
                "path": os.path.join(vaultPath, "ObsidianTaskProvider.md"),
                # TODO: this file should be defined as a configuration variable
                "default": f"# Task list{os.linesep}{os.linesep}"
            },
            FileRegistry.LAST_RECEIVED_FILE: {
                "path": os.path.join(jsonPath, "import.dat"),
                "default": defaultTaskJson
            },
        }

        self.vaultPaths: dict[VaultRegistry, str] = {
            VaultRegistry.OBSIDIAN: vaultPath
        }

    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        try:
            with open(str(self.filePaths[fileRegistry]["path"]), "r", errors="ignore") as file:
                return file.read()
        except FileNotFoundError:
            print(f"File not found: {self.filePaths[fileRegistry]['path']}")
            self.__createFile(fileRegistry)
            return str(self.filePaths[fileRegistry]["default"])

    def writeFileContent(self,
                         fileRegistry: FileRegistry, content: str) -> None:
        with open(str(self.filePaths[fileRegistry]["path"]), 'w+') as file:
            file.write(content)

    def readFileContentJson(self, fileRegistry: FileRegistry) -> FileContentJson:
        try:
            with open(str(self.filePaths[fileRegistry]["path"]), "r", errors="ignore") as file:
                return dict(json.load(file))
        except FileNotFoundError:
            print(f"File not found: {self.filePaths[fileRegistry]['path']}")
            self.__createFile(fileRegistry)
            retval: FileContentJson = json.loads(str(self.filePaths[fileRegistry]["default"]))
            return retval
        
    def readStatisticsFileContentJson(self) -> StatisticsFileContentJson:
        try:
            with open(str(self.filePaths[FileRegistry.STATISTICS_JSON]["path"]), "r", errors="ignore") as file:
                return dict(json.load(file))
        except FileNotFoundError:
            print(f"File not found: {self.filePaths[FileRegistry.STATISTICS_JSON]['path']}")
            self.__createFile(FileRegistry.STATISTICS_JSON)
            retval: StatisticsFileContentJson = json.loads(str(self.filePaths[FileRegistry.STATISTICS_JSON]["default"]))
            return retval

    def __createFile(self, fileRegistry: FileRegistry) -> None:
        with open(str(self.filePaths[fileRegistry]["path"]), 'w+') as file:
            file.write(str(self.filePaths[fileRegistry]["default"]))

    @typing.no_type_check
    def writeFileContentJson(self,
                             fileRegistry: FileRegistry,
                             content: FileContent | StatisticsFileContentJson) -> None:
        with open(str(self.filePaths[fileRegistry]["path"]), 'w+') as file:
            json.dump(dict(content), file, indent=4)

    def getVaultFileLines(self,
                          vaultRegistry: VaultRegistry,
                          relativePath: str) -> list[str]:
        filePath = os.path.join(self.vaultPaths[vaultRegistry], relativePath)
        with open(filePath, "r", errors="ignore") as file:
            return file.readlines()

    def writeVaultFileLines(self,
                            vaultRegistry: VaultRegistry,
                            relativePath: str,
                            lines: list[str]) -> None:
        filePath = os.path.join(self.vaultPaths[vaultRegistry], relativePath)
        with open(filePath, "w") as file:
            file.writelines(lines)

    # Get all files in vauld directory and subdirectories, returns a tuple with the path and the last modification time
    def getVaultFiles(self, vaultRegistry: VaultRegistry) -> list[tuple[str, float]]:
        files = []
        for root, _, filenames in os.walk(self.vaultPaths[vaultRegistry]):
            for filename in filenames:
                full_file_path = os.path.join(root, filename)
                file_path = full_file_path[len(self.vaultPaths[vaultRegistry]):]
                last_mod_time = os.path.getmtime(full_file_path)
                files.append((file_path, last_mod_time))
        return files
