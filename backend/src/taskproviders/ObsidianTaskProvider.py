import datetime
import json
import re
import threading

from src.Utils import TaskJsonType

from ..Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from ..Interfaces.ITaskProvider import ITaskProvider
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..taskmodels.ObsidianTaskModel import ObsidianTaskModel
from ..taskmodels.TaskIdentity import fallback_task_id, validate_task_id
from .TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError, MissingTaskIdentityError
from typing import Callable, List


class ObsidianTaskProvider(ITaskProvider):
    _TASK_LINE = re.compile(r"^(\s*-\s+\[)([ xX])(\])([ \t]*)(.*?)(\r?\n)?$")
    _TASK_METADATA = re.compile(r"\[([^\]:]+)::\s*([^\]]*)\]")
    _NEW_TASK_FILE = "ObsidianTaskProvider.md"
    _METADATA_ORDER = ("track", "starts", "due", "severity", "remaining_cost", "invested", "calm", "raised", "waited", "id")

    def __init__(self, taskJsonProvider: ITaskJsonProvider, fileBroker: IFileBroker, disableThreading: bool = False):
        self.TaskJsonProvider = taskJsonProvider
        self.fileBroker = fileBroker
        self.serviceRunning = True
        self.lastJson: TaskJsonType = {}
        self.lastTaskList: List[ITaskModel] = []
        self.onTaskListUpdatedCallbacks: list[Callable[[], None]] = []
        self.__discoveryLock = threading.Lock()
        self.__pendingNewLines: dict[int, str] = {}
        self.__disableThreading = disableThreading
        if not self.__disableThreading:
            self.service = threading.Thread(target=self.__serviceThread)
            self.service.start()

    def dispose(self) -> None:
        if not self.__disableThreading:
            self.serviceRunning = False
            self.service.join()

    def __serviceThread(self) -> None:
        while self.serviceRunning:
            previousTaskList = self.lastTaskList
            try:
                newTaskList = self.discoverTasks()
            except Exception as error:
                print(f"Task discovery failed: {error.__class__.__name__}: {error}")
            else:
                if not self.compare(previousTaskList, newTaskList):
                    for callback in self.onTaskListUpdatedCallbacks:
                        callback()
            threading.Event().wait(10)

    def __buildTaskList(self, obsidianJson: TaskJsonType, include_completed: bool = False) -> List[ITaskModel]:
        taskListJson = obsidianJson.get("tasks", [])
        taskList: List[ITaskModel] = []
        for task in taskListJson:
            if not include_completed and task["status"] == "x":
                continue
            obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], int(task["starts"]), int(task["due"]), float(task["severity"]), float(task["total_cost"]), float(task["effort_invested"]), task["status"], task["file"], int(task["line"]), task["calm"], task.get("raised"), task.get("waited"), task.get("id"))
            taskList.append(obsidianTask)
        return taskList

    def getTaskList(self, include_completed: bool = False) -> List[ITaskModel]:
        """Return a fresh parsed view without running discovery or writing."""
        obsidianJson = self.TaskJsonProvider.getJson()
        return self.__buildTaskList(obsidianJson, include_completed)

    def discoverTasks(self) -> List[ITaskModel]:
        """Run the explicit discovery hook and refresh its maintenance snapshot."""
        with self.__discoveryLock:
            discoveredJson = self.TaskJsonProvider.discover()
            self.lastJson = discoveredJson
            self.lastTaskList = self.__buildTaskList(discoveredJson)
        return self.lastTaskList

    def getTaskListAttribute(self, string: str) -> list[dict[str, str]]:
        value = self.TaskJsonProvider.getJson().get(string, [])
        if not isinstance(value, list):
            raise TypeError(f"Task data attribute '{string}' must be a list")
        return value

    def discardPendingTaskReservations(self) -> None:
        """Release locations prepared for new tasks that were not saved."""
        self.__pendingNewLines.clear()

    def _getTaskLine(self, task: ITaskModel, task_id: str | None = None) -> str:
        description = self._getTaskText(task)
        start = str(task.getStart())
        due = str(task.getDue())
        severity = task.getSeverity()
        totalCost = task.getTotalCost().as_pomodoros()
        investedEffort = task.getInvestedEffort().as_pomodoros()
        status = task.getStatus()
        calm = "true" if task.getCalm() else "false"

        raises = task.getEventRaised()
        raises_str = f", [raised:: {raises}]" if isinstance(raises, str) else ""

        waits = task.getEventWaited()
        waits_str = f", [waited:: {waits}]" if isinstance(waits, str) else ""

        task_id = validate_task_id(task_id) if task_id is not None else self._get_task_uid(task)
        return f"- [{status}] {description} [track:: {task.getContext()}], [starts:: {start}], [due:: {due}], [severity:: {severity}], [remaining_cost:: {totalCost + investedEffort}], [invested:: {investedEffort}], [calm:: {calm}]{raises_str}{waits_str}, [id:: {task_id}]\n"

    @staticmethod
    def _getTaskText(task: ITaskModel) -> str:
        get_task_text = getattr(task, "getTaskText", None)
        if callable(get_task_text):
            value = get_task_text()
            if isinstance(value, str):
                return value
        get_raw_description = getattr(task, "getRawDescription", None)
        if callable(get_raw_description):
            value = get_raw_description()
            if isinstance(value, str):
                return value
        context = task.getContext()
        return task.getDescription().split("@")[0].replace(f"({context})", "").strip()

    def _get_task_uid(self, task: ITaskModel) -> str:
        return validate_task_id(task.getTaskUID())

    def saveTask(self, task: ITaskModel) -> None:
        if isinstance(task, ObsidianTaskModel) and self.__pendingNewLines.get(task.getLine()) == task.getTaskUID():
            self._save_reserved_new_task(task)
            return

        task_id = self._get_task_uid(task)
        locations = self._scan_vault_task_identities()
        matches = [location for location in locations if location["id"] == task_id]
        if not matches:
            raise MissingTaskIdentityError("No current Markdown task matches the requested identifier")
        if len(matches) > 1:
            raise AmbiguousTaskIdentityError("More than one current Markdown task matches the requested identifier")

        location = matches[0]
        file = str(location["file"])
        line_number = int(location["line"])
        file_lines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)
        if line_number >= len(file_lines):
            raise MissingTaskIdentityError("The Markdown task moved while it was being saved")
        file_lines[line_number] = self._merge_task_line(file_lines[line_number], task, task_id)
        self.fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, file, file_lines)
        if isinstance(task, ObsidianTaskModel):
            task.setFile(file)
            task.setLine(line_number)
            task.setTaskUID(task_id)

    def _reserve_new_location(self, description: str) -> tuple[int, str]:
        file_content = self.fileBroker.readFileContent(FileRegistry.OBSIDIAN_TASKS_MD)
        lines = file_content.splitlines(keepends=True)
        line_number = len(lines) + len(self.__pendingNewLines)
        task_id = fallback_task_id(description, self._NEW_TASK_FILE, line_number)
        existing_ids = {str(location["id"]) for location in self._scan_vault_task_identities()}
        if task_id in existing_ids or task_id in self.__pendingNewLines.values():
            raise AmbiguousTaskIdentityError("The prepared Markdown task identifier is already in use")
        self.__pendingNewLines[line_number] = task_id
        return line_number, task_id

    def _save_reserved_new_task(self, task: ObsidianTaskModel) -> None:
        line_number = task.getLine()
        file_content = self.fileBroker.readFileContent(FileRegistry.OBSIDIAN_TASKS_MD)
        lines = file_content.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += "\n"
        if line_number != len(lines):
            raise MissingTaskIdentityError("The prepared Markdown task location is no longer available")
        task_id = validate_task_id(self.__pendingNewLines[line_number])
        current_matches = [
            location
            for location in self._scan_vault_task_identities()
            if location["id"] == task_id
        ]
        if current_matches:
            raise AmbiguousTaskIdentityError("The prepared Markdown task identifier is already in use")
        task.setTaskUID(task_id)
        lines.append(self._getTaskLine(task, task_id))
        self.fileBroker.writeFileContent(FileRegistry.OBSIDIAN_TASKS_MD, "".join(lines))
        self.__pendingNewLines.pop(line_number, None)

    def _scan_vault_task_identities(self) -> list[dict[str, str | int]]:
        locations: list[dict[str, str | int]] = []
        for file, _ in self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN):
            if not file.lower().endswith(".md"):
                continue
            normalized_file = file.replace("\\", "/")
            for line_number, line in enumerate(self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)):
                match = self._TASK_LINE.match(line)
                if match is None:
                    continue
                body = match.group(5)
                metadata = list(self._TASK_METADATA.finditer(body))
                text = body[:metadata[0].start()].strip() if metadata else body.strip()
                declared_ids = [
                    validate_task_id(item.group(2).strip())
                    for item in metadata
                    if item.group(1).strip() == "id"
                ]
                if len(set(declared_ids)) > 1:
                    raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
                task_id = declared_ids[0] if declared_ids else fallback_task_id(text, normalized_file, line_number)
                locations.append({"id": task_id, "file": normalized_file, "line": line_number})
        return locations

    def _merge_task_line(self, original_line: str, task: ITaskModel, task_id: str) -> str:
        match = self._TASK_LINE.match(original_line)
        if match is None:
            raise MissingTaskIdentityError("The Markdown task line is no longer valid")
        task_id = validate_task_id(task_id)
        description = self._getTaskText(task)
        newline = match.group(6) or ""
        source_status = "x" if match.group(2).lower() == "x" else " "
        wanted_status = "x" if task.getStatus().lower() == "x" else " "
        status = match.group(2) if source_status == wanted_status else wanted_status
        prefix = f"{match.group(1)}{status}{match.group(3)}{match.group(4)}"
        body = match.group(5)
        metadata = list(self._TASK_METADATA.finditer(body))
        updates = {
            "track": str(task.getContext()),
            "starts": str(task.getStart()),
            "start": str(task.getStart()),
            "due": str(task.getDue()),
            "severity": str(task.getSeverity()),
            "remaining_cost": str(task.getTotalCost().as_pomodoros() + task.getInvestedEffort().as_pomodoros()),
            "invested": str(task.getInvestedEffort().as_pomodoros()),
            "calm": "true" if task.getCalm() else "false",
            "id": task_id,
        }
        if isinstance(task.getEventRaised(), str):
            updates["raised"] = str(task.getEventRaised())
        if isinstance(task.getEventWaited(), str):
            updates["waited"] = str(task.getEventWaited())

        replaced_keys: set[str] = set()
        suffix_start = metadata[0].start() if metadata else len(body)
        title_and_separator = body[:suffix_start]
        separator_match = re.search(r"[ \t]*$", title_and_separator)
        separator = separator_match.group(0) if separator_match else ""
        suffix = body[suffix_start:]
        rewritten_parts: list[str] = []
        cursor = 0
        for item in self._TASK_METADATA.finditer(suffix):
            rewritten_parts.append(suffix[cursor:item.start()])
            key = item.group(1).strip()
            if key in updates:
                rewritten_parts.append(f"[{item.group(1)}:: {updates[key]}]")
                replaced_keys.add(key)
            elif key in ("raised", "waited"):
                replaced_keys.add(key)
            else:
                rewritten_parts.append(item.group(0))
            cursor = item.end()
        rewritten_parts.append(suffix[cursor:])
        suffix = "".join(rewritten_parts)

        missing = [
            f"[{key}:: {updates[key]}]"
            for key in self._METADATA_ORDER
            if key in updates and key not in replaced_keys
        ]
        if not isinstance(task.getEventRaised(), str) and "raised" not in replaced_keys:
            missing = [value for value in missing if not value.startswith("[raised::")]
        if not isinstance(task.getEventWaited(), str) and "waited" not in replaced_keys:
            missing = [value for value in missing if not value.startswith("[waited::")]
        updated_body = description + separator + suffix
        if missing:
            if suffix:
                updated_body += " " + " ".join(missing)
            else:
                updated_body += (" " if updated_body else "") + " ".join(missing)
        return prefix + updated_body + newline

    def createDefaultTask(self, description: str) -> ObsidianTaskModel:
        starts = int(datetime.datetime.now().timestamp() * 1e3)
        due = int(datetime.datetime.today().timestamp() * 1e3)
        starts = starts - starts % 60000
        due = due - due % 60000

        severity = 1.0
        invested = 0.0
        status = " "
        calm = "False"

        line_number, task_id = self._reserve_new_location(description)
        task = ObsidianTaskModel(description, "inbox", starts, due, 1, severity, invested, status, self._NEW_TASK_FILE, line_number, calm, None, None, task_id)
        return task

    def getTaskMetadata(self, task: ITaskModel) -> str:
        if not isinstance(task, ObsidianTaskModel):
            return ""
        
        file = task.getFile()
        line = task.getLine()
        fileLines = fileLines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)

        metadata: list[str] = []
        for i in range(max(line, 0), min(line + 5, len(fileLines))):
            metadata.append(fileLines[i])

        return "".join(metadata)

    def registerTaskListUpdatedCallback(self, callback: Callable[[], None]) -> None:
        self.onTaskListUpdatedCallbacks.append(callback)

    def compare(self, list_a: list[ITaskModel], list_b: list[ITaskModel]) -> bool:
        if len(list_a) != len(list_b):
            return False
        for i in range(len(list_a)):
            if list_a[i] != list_b[i]:
                return False
        return True

    def _exportJson(self) -> bytearray:
        self.lastJson = self.TaskJsonProvider.getJson()
        taskList = self.__buildTaskList(self.lastJson, include_completed=True)
        jsonStr = self.__generateExportJson(taskList)
        return bytearray(jsonStr, "utf-8")

    def exportTasks(self, selectedFormat: str) -> bytearray:
        supportedFormats: dict[str, Callable[[], bytearray]] = {
            "json": self._exportJson,
        }

        return supportedFormats[selectedFormat]()

    def importTasks(self, selectedFormat: str) -> None:
        raise NotImplementedError("Importing tasks is not supported for ObsidianTaskProvider")

    def __generateExportJson(self, taskList: List[ITaskModel]) -> str:
        tasks: list[dict[str, str]] = []
        for task in taskList:
            taskDict = {
                "id": task.getTaskUID(),
                "description": task.getDescription(),
                "context": task.getContext(),
                "start": str(task.getStart().as_int()),
                "due": str(task.getDue().as_int()),
                "severity": str(task.getSeverity()),
                "totalCost": str(task.getTotalCost().as_pomodoros()),
                "investedEffort": str(task.getInvestedEffort().as_pomodoros()),
                "status": str(task.getStatus()),
                "calm": str(task.getCalm())
            }
            tasks.append(taskDict)
        return json.dumps({
            "tasks": tasks
        }, indent=4)
