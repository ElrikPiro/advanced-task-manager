import json
import os
import typing
from io import StringIO
from typing import Any, Callable, TypeVar, cast
from .AtomicFileStore import AtomicFileStore, AtomicWriteError
from .MutationCoordinator import MutationCoordinator
from .Utils import FileContent, FileContentJson, StatisticsFileContentJson, WorkLogEntry
from .Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from .taskmodels.TaskIdentity import InvalidTaskIdentityError

T = TypeVar("T")


class _VaultFileInventory(list[tuple[str, float]]):
    """Public path/mtime pairs with a stronger same-walk cache signature."""

    def __init__(self) -> None:
        super().__init__()
        self._signatures: dict[str, tuple[int, int, int, int]] = {}


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
        self._vault_commit_listeners: list[Callable[[str, list[str] | None, tuple[int, int, int, int] | None], None]] = []
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
            FileRegistry.NOTIFICATIONS_JSON: {
                "path": os.path.join(jsonPath, "notifications.json"),
                "default": ""
            },
        }

        self.vaultPaths: dict[VaultRegistry, str] = {
            VaultRegistry.OBSIDIAN: vaultPath
        }

    def getFilePath(self, fileRegistry: FileRegistry) -> str:
        return str(self.filePaths[fileRegistry]["path"])

    def registerVaultFileCommitListener(
        self,
        callback: Callable[[str, list[str] | None, tuple[int, int, int, int] | None], None],
    ) -> None:
        """Register a listener for committed Markdown changes inside the vault."""
        if callback not in self._vault_commit_listeners:
            self._vault_commit_listeners.append(callback)

    def _vault_relative_path(self, file_path: str) -> str | None:
        vault_path = os.path.abspath(self.vaultPaths[VaultRegistry.OBSIDIAN])
        absolute_path = os.path.abspath(file_path)
        try:
            if os.path.commonpath((vault_path, absolute_path)) != vault_path:
                return None
        except ValueError:
            return None
        return os.path.relpath(absolute_path, vault_path).replace("\\", "/")

    def _vault_signature(self, file_path: str, expected_content: bytes) -> tuple[int, int, int, int] | None:
        try:
            with open(file_path, "rb") as file:
                before = os.fstat(file.fileno())
                actual_content = file.read()
                after = os.fstat(file.fileno())
            current = os.stat(file_path)
        except OSError:
            return None
        signature = (after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_ino)
        current_signature = (current.st_mtime_ns, current.st_ctime_ns, current.st_size, current.st_ino)
        before_signature = (before.st_mtime_ns, before.st_ctime_ns, before.st_size, before.st_ino)
        if actual_content != expected_content or before_signature != signature or current_signature != signature:
            return None
        return (
            *signature,
        )

    def _notify_vault_file_commit(
        self,
        file_path: str,
        lines: list[str] | None,
        *,
        uncertain: bool = False,
        expected_content: bytes | None = None,
    ) -> None:
        relative_path = self._vault_relative_path(file_path)
        if relative_path is None or not relative_path.lower().endswith(".md"):
            return
        signature = (
            None
            if uncertain or expected_content is None
            else self._vault_signature(file_path, expected_content)
        )
        for callback in tuple(self._vault_commit_listeners):
            callback(relative_path, None if uncertain else list(lines or []), signature)

    def readFileContent(self, fileRegistry: FileRegistry) -> str:
        try:
            with open(str(self.filePaths[fileRegistry]["path"]), "r", encoding="utf-8", newline="") as file:
                return file.read()
        except FileNotFoundError:
            return str(self.filePaths[fileRegistry]["default"])

    def writeFileContent(self,
                         fileRegistry: FileRegistry, content: str) -> None:
        file_path = str(self.filePaths[fileRegistry]["path"])

        def write() -> None:
            try:
                self._atomicFileStore.write(
                    file_path,
                    content.encode("utf-8"),
                    self.__validatorFor(fileRegistry),
                )
            except AtomicWriteError as error:
                if error.effects_state == "unknown" or error.replaced:
                    self._notify_vault_file_commit(file_path, None, uncertain=True)
                raise
            if fileRegistry == FileRegistry.OBSIDIAN_TASKS_MD:
                self._notify_vault_file_commit(
                    file_path,
                    StringIO(content, newline="").readlines(),
                    expected_content=content.encode("utf-8"),
                )

        self._run_mutation(write)

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

        def commit_update() -> bytes:
            try:
                committed = self._atomicFileStore.update(
                    file_path,
                    update,
                    default,
                    self.__validatorFor(fileRegistry),
                )
            except AtomicWriteError as error:
                if error.effects_state == "unknown" or error.replaced:
                    self._notify_vault_file_commit(file_path, None, uncertain=True)
                raise
            if fileRegistry == FileRegistry.OBSIDIAN_TASKS_MD:
                self._notify_vault_file_commit(
                    file_path,
                    StringIO(committed.decode("utf-8"), newline="").readlines(),
                    expected_content=committed,
                )
            return committed

        saved = self._run_mutation(commit_update)
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

        def write() -> None:
            try:
                self._atomicFileStore.write(filePath, content, self.__validateUtf8)
            except AtomicWriteError as error:
                if error.effects_state == "unknown" or error.replaced:
                    self._notify_vault_file_commit(filePath, None, uncertain=True)
                raise
            self._notify_vault_file_commit(filePath, list(lines), expected_content=content)
        self._run_mutation(write)

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

        def commit_update() -> bytes:
            try:
                committed = self._atomicFileStore.update(file_path, update, b"", self.__validateUtf8)
            except AtomicWriteError as error:
                if error.effects_state == "unknown" or error.replaced:
                    self._notify_vault_file_commit(file_path, None, uncertain=True)
                raise
            self._notify_vault_file_commit(
                file_path,
                StringIO(committed.decode("utf-8"), newline="").readlines(),
                expected_content=committed,
            )
            return committed
        saved = self._run_mutation(commit_update)
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

        def create() -> bool:
            try:
                created = self._atomicFileStore.create_if_absent(file_path, content, self.__validateUtf8)
            except AtomicWriteError as error:
                if error.effects_state == "unknown" or error.replaced:
                    self._notify_vault_file_commit(file_path, None, uncertain=True)
                raise
            if created:
                self._notify_vault_file_commit(file_path, list(lines), expected_content=content)
            return created
        return self._run_mutation(create)

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
            FileRegistry.NOTIFICATIONS_JSON,
        }
        if fileRegistry in json_registries:
            def validate_json(content: bytes) -> None:
                FileBroker.__parseJsonBytes(fileRegistry, content)

            return validate_json
        return FileBroker.__validateUtf8

    # Get all files in vauld directory and subdirectories, returns a tuple with the path and the last modification time
    def getVaultFiles(self, vaultRegistry: VaultRegistry) -> list[tuple[str, float]]:
        return self._getVaultFiles(vaultRegistry, None)

    def getVaultFilesCancellable(
        self,
        vaultRegistry: VaultRegistry,
        should_stop: Callable[[], bool],
    ) -> list[tuple[str, float]]:
        """Inventory a vault while allowing a stopping refresh worker to yield."""
        return self._getVaultFiles(vaultRegistry, should_stop)

    def _getVaultFiles(
        self,
        vaultRegistry: VaultRegistry,
        should_stop: Callable[[], bool] | None,
    ) -> list[tuple[str, float]]:
        files = _VaultFileInventory()
        vault_path = self.vaultPaths[vaultRegistry]
        for root, _, filenames in os.walk(self.vaultPaths[vaultRegistry]):
            if should_stop is not None and should_stop():
                return files
            for filename in filenames:
                if should_stop is not None and should_stop():
                    return files
                if AtomicFileStore.is_temporary_file_name(filename):
                    continue
                full_file_path = os.path.join(root, filename)
                file_path = os.path.relpath(full_file_path, vault_path)
                try:
                    stat_result = os.stat(full_file_path)
                except FileNotFoundError:
                    continue
                files.append((file_path, stat_result.st_mtime))
                files._signatures[file_path] = (
                    stat_result.st_mtime_ns,
                    stat_result.st_ctime_ns,
                    stat_result.st_size,
                    stat_result.st_ino,
                )
        return files
