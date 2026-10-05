import json
import os
import typing
from io import StringIO
from typing import Any, Callable, TypeVar, cast
from .AtomicFileStore import AtomicFileStore
from .MutationCoordinator import MutationCoordinator
from .Utils import FileContent, FileContentJson, StatisticsFileContentJson, WorkLogEntry
from .Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from .taskmodels.TaskIdentity import InvalidTaskIdentityError

T = TypeVar("T")


class FileBroker(IFileBroker):
    def __init__(
        self,
        jsonPath: str,
        appdata: str,
        vaultPath: str,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        self._atomicFileStore = AtomicFileStore()
        self.mutation_coordinator = mutation_coordinator
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

    def getFilePath(self, fileRegistry: FileRegistry) -> str:
        return str(self.filePaths[fileRegistry]["path"])

    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        try:
            with open(str(self.filePaths[fileRegistry]["path"]), "r", encoding="utf-8", newline="") as file:
                return file.read()
        except FileNotFoundError:
            return str(self.filePaths[fileRegistry]["default"])

    def writeFileContent(self,
                         fileRegistry: FileRegistry, content: str) -> None:
        file_path = str(self.filePaths[fileRegistry]["path"])
        self._run_mutation(lambda: self._atomicFileStore.write(
            file_path,
            content.encode("utf-8"),
            self.__validatorFor(fileRegistry),
        ))

    def updateFileContent(self, fileRegistry: FileRegistry, updater: Callable[[str], str]) -> str:
        """Reapply a text mutation to the latest file snapshot and return saved text."""
        file_path = str(self.filePaths[fileRegistry]["path"])
        default = str(self.filePaths[fileRegistry]["default"]).encode("utf-8")

        def update(current: bytes | None) -> bytes:
            current_text = (current if current is not None else default).decode("utf-8")
            updated_text = updater(current_text)
            if not isinstance(updated_text, str):
                raise TypeError("Text updater must return a string")
            return updated_text.encode("utf-8")

        saved = self._run_mutation(lambda: self._atomicFileStore.update(
            file_path,
            update,
            default,
            self.__validatorFor(fileRegistry),
        ))
        return saved.decode("utf-8")

    def readFileContentJson(self, fileRegistry: FileRegistry) -> FileContentJson:
        raw = self.readFileContent(fileRegistry)
        value = json.loads(
            raw,
            object_pairs_hook=self.__rejectRepeatedIdKeys,
            parse_constant=self.__rejectNonFiniteJsonConstant,
        )
        if not isinstance(value, dict):
            raise TypeError("JSON file content must be an object")
        return cast(FileContentJson, value)

    @staticmethod
    def __rejectRepeatedIdKeys(pairs: list[tuple[str, typing.Any]]) -> dict[str, typing.Any]:
        result: dict[str, typing.Any] = {}
        for key, value in pairs:
            if key == "id" and key in result:
                raise InvalidTaskIdentityError("A task object declares its ID more than once")
            result[key] = value
        return result

    @staticmethod
    def __rejectNonFiniteJsonConstant(value: str) -> typing.NoReturn:
        raise ValueError(f"Invalid non-finite JSON number: {value}")
        
    def readStatisticsFileContentJson(self) -> StatisticsFileContentJson:
        raw = self.readFileContent(FileRegistry.STATISTICS_JSON)
        value = json.loads(raw, parse_constant=self.__rejectNonFiniteJsonConstant)
        if not isinstance(value, dict):
            raise TypeError("Statistics file content must be an object")
        log: list[dict[str, Any]] = value.get("log", [])
        proper_log: list[WorkLogEntry] = []
        for entry in log:
            proper_log.append(WorkLogEntry(timestamp=int(entry["timestamp"]), work_units=float(entry["work_units"]), task=entry["task"]))
        value["log"] = proper_log
        return cast(StatisticsFileContentJson, value)

    def updateFileContentJson(
        self,
        fileRegistry: FileRegistry,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Reapply a JSON mutation to the latest valid object and return saved data."""
        file_path = str(self.filePaths[fileRegistry]["path"])
        default = str(self.filePaths[fileRegistry]["default"]).encode("utf-8")

        def update(current: bytes | None) -> bytes:
            source = current if current is not None else default
            value = self.__parseJsonBytes(fileRegistry, source)
            updated = updater(value)
            if not isinstance(updated, dict):
                raise TypeError("JSON updater must return an object")
            serialized = json.dumps(
                self.__serializableContent(updated),
                indent=4,
                allow_nan=False,
            )
            return serialized.encode("utf-8")

        def validate_json(content: bytes) -> None:
            self.__parseJsonBytes(fileRegistry, content)

        saved = self._run_mutation(lambda: self._atomicFileStore.update(
            file_path,
            update,
            default,
            validate_json,
        ))
        return self.__parseJsonBytes(fileRegistry, saved)

    def initializeFileContent(self, fileRegistry: FileRegistry) -> None:
        """Create a registered file with its default content if it is absent."""
        file_path = str(self.filePaths[fileRegistry]["path"])
        default = str(self.filePaths[fileRegistry]["default"]).encode("utf-8")
        self._run_mutation(lambda: self._atomicFileStore.create_if_absent(
            file_path,
            default,
            self.__validatorFor(fileRegistry),
        ))

    @typing.no_type_check
    def writeFileContentJson(self,
                             fileRegistry: FileRegistry,
                             content: FileContent | StatisticsFileContentJson) -> None:
        file_path = str(self.filePaths[fileRegistry]["path"])
        serializable_content = self.__serializableContent(content)
        serialized = json.dumps(serializable_content, indent=4, allow_nan=False)
        self._run_mutation(lambda: self._atomicFileStore.write(
            file_path,
            serialized.encode("utf-8"),
            self.__validatorFor(fileRegistry),
        ))

    def getVaultFileLines(self,
                          vaultRegistry: VaultRegistry,
                          relativePath: str) -> list[str]:
        filePath = os.path.join(self.vaultPaths[vaultRegistry], relativePath)
        with open(filePath, "r", encoding="utf-8", newline="") as file:
            return file.readlines()

    def writeVaultFileLines(self,
                            vaultRegistry: VaultRegistry,
                            relativePath: str,
                            lines: list[str]) -> None:
        filePath = os.path.join(self.vaultPaths[vaultRegistry], relativePath)
        content = "".join(lines).encode("utf-8")
        self._run_mutation(lambda: self._atomicFileStore.write(filePath, content, self.__validateUtf8))

    def updateVaultFileLines(
        self,
        vaultRegistry: VaultRegistry,
        relativePath: str,
        updater: Callable[[list[str]], list[str]],
    ) -> list[str]:
        """Reapply a line mutation to the latest vault file and return saved lines."""
        file_path = os.path.join(self.vaultPaths[vaultRegistry], relativePath)

        def update(current: bytes | None) -> bytes:
            text = (current if current is not None else b"").decode("utf-8")
            updated_lines = updater(StringIO(text, newline="").readlines())
            if not isinstance(updated_lines, list) or any(not isinstance(line, str) for line in updated_lines):
                raise TypeError("Vault line updater must return a list of strings")
            return "".join(updated_lines).encode("utf-8")

        saved = self._run_mutation(lambda: self._atomicFileStore.update(file_path, update, b"", self.__validateUtf8))
        return StringIO(saved.decode("utf-8"), newline="").readlines()

    def createVaultFileLinesIfAbsent(
        self,
        vaultRegistry: VaultRegistry,
        relativePath: str,
        lines: list[str],
    ) -> bool:
        """Create a vault note only if its path is still unused."""
        file_path = os.path.join(self.vaultPaths[vaultRegistry], relativePath)
        content = "".join(lines).encode("utf-8")
        return self._run_mutation(lambda: self._atomicFileStore.create_if_absent(file_path, content, self.__validateUtf8))

    def __ensureParentDirectory(self, file_path: str) -> None:
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    def cleanupAtomicTemps(self, directories: list[str] | None = None) -> int:
        """Remove only abandoned temporaries beneath configured data directories."""
        roots = directories
        if roots is None:
            roots = [os.path.dirname(str(entry["path"])) for entry in self.filePaths.values()]
            roots.extend(self.vaultPaths.values())
        return self._run_mutation(lambda: AtomicFileStore.cleanup_temporary_files(roots))

    def _run_mutation(self, callback: Callable[[], T]) -> T:
        """Serialize storage changes and run nested writes inline in their turn."""
        if self.mutation_coordinator is None:
            return callback()
        return self.mutation_coordinator.run_or_inline(callback)

    @staticmethod
    def __validateUtf8(content: bytes) -> None:
        content.decode("utf-8")

    @staticmethod
    @typing.no_type_check
    def __serializableContent(content: FileContent | StatisticsFileContentJson) -> dict[str, Any]:
        serializable_content = dict(content)
        if "log" in serializable_content and isinstance(serializable_content["log"], list):
            serializable_content["log"] = [
                entry.__dict__() if hasattr(entry, "__dict__") and callable(getattr(entry, "__dict__"))
                else entry if isinstance(entry, dict)
                else entry.__dict__ if hasattr(entry, "__dict__")
                else str(entry)
                for entry in serializable_content["log"]
            ]
        return serializable_content

    @staticmethod
    def __parseJsonBytes(fileRegistry: FileRegistry, content: bytes) -> dict[str, Any]:
        decoded = content.decode("utf-8")
        if fileRegistry == FileRegistry.STATISTICS_JSON:
            value = json.loads(decoded, parse_constant=FileBroker.__rejectNonFiniteJsonConstant)
        else:
            value = json.loads(
                decoded,
                object_pairs_hook=FileBroker.__rejectRepeatedIdKeys,
                parse_constant=FileBroker.__rejectNonFiniteJsonConstant,
            )
        if not isinstance(value, dict):
            raise TypeError("JSON file content must be an object")
        return value

    @staticmethod
    def __validatorFor(fileRegistry: FileRegistry) -> Callable[[bytes], None]:
        json_registries = {
            FileRegistry.STANDALONE_TASKS_JSON,
            FileRegistry.STATISTICS_JSON,
            FileRegistry.OBSIDIAN_TASKS_JSON,
            FileRegistry.LAST_RECEIVED_FILE,
        }
        if fileRegistry in json_registries:
            def validate_json(content: bytes) -> None:
                FileBroker.__parseJsonBytes(fileRegistry, content)

            return validate_json
        return FileBroker.__validateUtf8

    # Get all files in vauld directory and subdirectories, returns a tuple with the path and the last modification time
    def getVaultFiles(self, vaultRegistry: VaultRegistry) -> list[tuple[str, float]]:
        files = []
        vault_path = self.vaultPaths[vaultRegistry]
        for root, _, filenames in os.walk(self.vaultPaths[vaultRegistry]):
            for filename in filenames:
                if AtomicFileStore.is_temporary_file_name(filename):
                    continue
                full_file_path = os.path.join(root, filename)
                file_path = os.path.relpath(full_file_path, vault_path)
                try:
                    last_mod_time = os.path.getmtime(full_file_path)
                except FileNotFoundError:
                    continue
                files.append((file_path, last_mod_time))
        return files
