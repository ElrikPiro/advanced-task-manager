import datetime
import threading
from ..Interfaces.ITaskProvider import ITaskProvider
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry
from ..taskmodels.TaskModel import TaskModel
from ..taskmodels.TaskIdentity import fallback_task_id, validate_task_id
from .TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError, MissingTaskIdentityError
from typing import Any, Callable, List, cast
import json
from copy import deepcopy
from src.Utils import TaskJsonType


class ConfirmedTaskRefreshError(RuntimeError):
    """A persisted task could not be materialized from the confirmed document."""

    effects_state = "unknown"


class TaskPrepareError(ValueError):
    """The latest task record could not be materialized before publication."""

    effects_state = "none"


class TaskProvider(ITaskProvider):

    def __init__(self, task_json_provider: ITaskJsonProvider, fileBroker: IFileBroker, disableThreading: bool = False):
        self.taskJsonProvider = task_json_provider
        self.fileBroker = fileBroker
        self.dict_task_list = self.taskJsonProvider.getJson()
        self.onTaskListUpdatedCallbacks: list[Callable[[], None]] = []
        self.__discoveryLock = threading.Lock()
        self.__pendingNewTasks: dict[int, dict[str, str]] = {}
        self.__pendingNewTaskIds: dict[int, str] = {}
        self.__disableThreading = disableThreading
        if not self.__disableThreading:
            self.serviceRunning = True
            self.service = threading.Thread(target=self.__serviceThread)
            self.service.start()

    def dispose(self) -> None:
        """
        Disposes the task provider.

        This method should be called when the task provider is no longer needed.
        It will stop the service thread if it is running allowing the python process to exit.
        """
        if not self.__disableThreading:
            self.serviceRunning = False
            self.service.join()

    def __serviceThread(self) -> None:
        """
        The service thread that will notify the registered callbacks every 10 seconds.
        """
        while self.serviceRunning:
            try:
                self.discoverTasks()
            except Exception as error:
                print(f"Task discovery failed: {error.__class__.__name__}: {error}")
            else:
                for callback in self.onTaskListUpdatedCallbacks:
                    callback()
            threading.Event().wait(10)

    def getTaskList(self, include_completed: bool = False) -> List[ITaskModel]:
        """
        Gets the task list.

        This method reads the task list from the json file and creates a list of task models from it.

        Returns:
            List[ITaskModel]: The task list."""
        newTaskJson = self.taskJsonProvider.getJson()
        self.dict_task_list = dict(newTaskJson)
        task_data = self.__getTaskRecords(newTaskJson)
        identity_path = self.__getIdentityPath()
        identities = [
            self.__resolveRecordIdentity(record, raw_index, identity_path)
            for raw_index, record in enumerate(task_data)
        ]
        self.dict_task_list["tasks"] = task_data if include_completed else []
        task_list: List[ITaskModel] = []
        for raw_index, task in enumerate(task_data):
            status = task["status"]
            if not include_completed and status == "x":
                continue
            task_list.append(self.createTaskFromDict(task, raw_index, identities[raw_index], identity_path))
            if not include_completed:
                self.dict_task_list["tasks"].append(task)
        return task_list

    def discoverTasks(self) -> List[ITaskModel]:
        """Explicitly reconcile provider discoveries, then return a fresh view."""
        with self.__discoveryLock:
            self.taskJsonProvider.discover()
        return self.getTaskList()

    def createTaskFromDict(self, dict_task: dict[str, str], index: int, task_id: str | None = None, identity_path: str | None = None) -> ITaskModel:
        """
        Creates a task model from a dictionary.

        This method creates a task model from a dictionary containing the task data.

        Params:
            dict_task: The dictionary containing the task data.
            index: The index of the task in the task list.
        """
        if identity_path is None:
            identity_path = self.__getIdentityPath()
        if task_id is None:
            task_id = self.__resolveRecordIdentity(dict_task, index, identity_path)
        else:
            task_id = validate_task_id(task_id)

        task = TaskModel(
            index=index,
            description=dict_task["description"],
            context=dict_task["context"],
            start=int(dict_task["start"]),
            due=int(dict_task["due"]),
            severity=float(dict_task["severity"]),
            totalCost=float(dict_task["totalCost"]),
            investedEffort=float(dict_task["investedEffort"]),
            status=dict_task["status"],
            calm=dict_task["calm"],
            project=dict_task.get("project", ""),
            raised=dict_task.get("raised"),
            waited=dict_task.get("waited"),
            task_id=task_id,
            identity_path=identity_path,
        )
        setattr(task, "_task_provider_baseline", self.__getTaskSaveFields(task))
        return task

    def __getIdentityPath(self) -> str:
        path = self.fileBroker.getFilePath(FileRegistry.STANDALONE_TASKS_JSON)
        if not isinstance(path, str):
            raise TypeError("Configured task file path must be a string")
        return path

    def __getTaskRecords(self, task_json: TaskJsonType) -> list[dict[str, str]]:
        if not isinstance(task_json, dict):
            raise TypeError("Task JSON document must be an object")
        records = task_json.get("tasks", [])
        if not isinstance(records, list):
            raise TypeError("Task data attribute 'tasks' must be a list")
        if any(not isinstance(record, dict) for record in records):
            raise TypeError("Every task record must be an object")
        return records

    def __resolveRecordIdentity(self, record: dict[str, str], index: int, identity_path: str) -> str:
        if "id" in record:
            return validate_task_id(record["id"])
        return fallback_task_id(record["description"], identity_path, index)

    def __resolveRecordIndexes(self, records: list[dict[str, str]], task_id: str, identity_path: str) -> list[int]:
        matches = [
            index
            for index, record in enumerate(records)
            if self.__resolveRecordIdentity(record, index, identity_path) == task_id
        ]
        return matches

    @staticmethod
    def __getTaskSaveFields(task: ITaskModel) -> dict[str, str | None]:
        get_raw_description = getattr(task, "getRawDescription", None)
        description = get_raw_description() if callable(get_raw_description) else task.getDescription().split(" @ ")[0].strip()
        return {
            "description": description,
            "context": task.getContext(),
            "start": str(task.getStart().as_int()),
            "due": str(task.getDue().as_int()),
            "severity": str(task.getSeverity()),
            "totalCost": str(task.getTotalCost().as_pomodoros()),
            "investedEffort": str(task.getInvestedEffort().as_pomodoros()),
            "status": task.getStatus(),
            "calm": "True" if task.getCalm() else "False",
            "project": task.getProject(),
            "raised": task.getEventRaised(),
            "waited": task.getEventWaited(),
        }

    def getTaskListAttribute(self, string: str) -> list[dict[str, str]]:
        value = self.taskJsonProvider.getJson().get(string, [])
        if not isinstance(value, list):
            raise TypeError(f"Task data attribute '{string}' must be a list")
        return value

    def saveTask(self, task: ITaskModel) -> None:
        """
        Saves a task.

        This method saves a task to the task list.

        Params:
            task: The task to be saved.
        """
        task_id = validate_task_id(task.getTaskUID())
        identity_path = self.__getIdentityPath()
        pending_index = next(
            (index for index, reserved_id in self.__pendingNewTaskIds.items() if reserved_id == task_id),
            None,
        )
        reserved_record = deepcopy(self.__pendingNewTasks[pending_index]) if pending_index is not None else None

        candidate_fields = self.__getTaskSaveFields(task)
        baseline_fields = getattr(task, "_task_provider_baseline", None)
        changed_fields = set(candidate_fields) if not isinstance(baseline_fields, dict) else {
            key for key, value in candidate_fields.items() if baseline_fields.get(key) != value
        }
        forced_fields: Any = getattr(task, "_task_provider_forced_fields", set())
        if isinstance(forced_fields, (set, frozenset, list, tuple)):
            changed_fields.update(key for key in forced_fields if isinstance(key, str) and key in candidate_fields)
        updated_fields = {
            key: value
            for key, value in candidate_fields.items()
            if key in changed_fields and key not in ("raised", "waited")
        }

        def prepare(current: TaskJsonType) -> TaskJsonType:
            task_json = deepcopy(current)
            task_records = self.__getTaskRecords(task_json)
            indexes = self.__resolveRecordIndexes(task_records, task_id, identity_path)

            if pending_index is not None and indexes:
                raise AmbiguousTaskIdentityError("Task ID conflicts with a pending new task")
            if len(indexes) > 1:
                raise AmbiguousTaskIdentityError("Task ID resolves to multiple stored tasks")
            if not indexes:
                if pending_index is None or pending_index != len(task_records) or reserved_record is None:
                    raise MissingTaskIdentityError("Task ID does not resolve to a stored task")
                record = deepcopy(reserved_record)
                task_records.append(record)
                record_index = pending_index
            else:
                record = task_records[indexes[0]]
                record_index = indexes[0]

            record.update(cast(dict[str, str], updated_fields))
            record["id"] = task_id
            if "raised" in changed_fields:
                if isinstance(candidate_fields["raised"], str):
                    record["raised"] = candidate_fields["raised"]
                else:
                    record.pop("raised", None)
            if "waited" in changed_fields:
                if isinstance(candidate_fields["waited"], str):
                    record["waited"] = candidate_fields["waited"]
                else:
                    record.pop("waited", None)
            task_json["tasks"] = task_records
            # Validate the complete model against the latest record before the
            # atomic helper stages any bytes.
            try:
                self.createTaskFromDict(record, record_index, task_id, identity_path)
            except InvalidTaskIdentityError:
                raise
            except Exception as error:
                raise TaskPrepareError("Updated task data is invalid") from error
            return task_json

        committed = self.taskJsonProvider.updateJson(prepare)
        try:
            committed_records = self.__getTaskRecords(committed)
            committed_indexes = self.__resolveRecordIndexes(committed_records, task_id, identity_path)
            if len(committed_indexes) != 1:
                raise MissingTaskIdentityError("Task could not be uniquely resolved in its confirmed document")
            refreshed = self.createTaskFromDict(
                committed_records[committed_indexes[0]],
                committed_indexes[0],
                task_id,
                identity_path,
            )
        except Exception as error:
            raise ConfirmedTaskRefreshError("Saved task could not be refreshed from the confirmed document") from error
        self.__copyTaskValues(refreshed, task)
        self.dict_task_list = deepcopy(committed)
        setattr(task, "_task_provider_forced_fields", set())
        if pending_index is not None:
            self.__pendingNewTasks.pop(pending_index, None)
            self.__pendingNewTaskIds.pop(pending_index, None)

    @staticmethod
    def __copyTaskValues(source: ITaskModel, target: ITaskModel) -> None:
        if isinstance(source, TaskModel) and isinstance(target, TaskModel):
            for attribute in (
                "_description", "_context", "_start", "_due", "_severity",
                "_totalCost", "_investedEffort", "_status", "_calm", "_project",
                "_index", "_task_id", "_identity_path", "_raised", "_waited",
                "_task_provider_baseline",
            ):
                setattr(target, attribute, getattr(source, attribute))
            return
        get_raw_description = getattr(source, "getRawDescription", None)
        target.setDescription(get_raw_description() if callable(get_raw_description) else source.getDescription())
        target.setContext(source.getContext())
        target.setStart(source.getStart())
        target.setDue(source.getDue())
        target.setSeverity(source.getSeverity())
        target.setTotalCost(source.getTotalCost())
        target.setInvestedEffort(source.getInvestedEffort())
        target.setStatus(source.getStatus())
        target.setCalm(source.getCalm())
        target.setEventRaised(source.getEventRaised())
        target.setEventWaited(source.getEventWaited())
        if hasattr(target, "_project"):
            setattr(target, "_project", source.getProject())
        if hasattr(target, "_task_id"):
            setattr(target, "_task_id", source.getTaskUID())
        setattr(target, "_task_provider_baseline", TaskProvider.__getTaskSaveFields(target))

    def createDefaultTask(self, description: str) -> ITaskModel:
        """
        Creates a default task.

        This method creates a default task with the given description.

        Params:
            description: The description of the task.
        """
        starts = int(datetime.datetime.now().timestamp() * 1e3)
        due = int(datetime.datetime.today().timestamp() * 1e3)
        starts = starts - starts % 60000
        due = due - due % 60000

        severity = 1.0
        invested = 0.0
        status = " "
        calm = "False"

        default_task = dict[str, str](
            description=description,
            context="inbox",
            start=str(starts),
            due=str(due),
            severity=str(severity),
            totalCost=str(1.0),
            investedEffort=str(invested),
            status=status,
            calm=calm,
            project=""
        )

        taskJson = deepcopy(self.taskJsonProvider.getJson())
        task_records = list(self.__getTaskRecords(taskJson))
        pending_indexes = sorted(self.__pendingNewTasks)
        expected_indexes = list(range(len(task_records), len(task_records) + len(pending_indexes)))
        if pending_indexes != expected_indexes:
            raise MissingTaskIdentityError("A prepared task location changed before it could be saved")
        task_records.extend(self.__pendingNewTasks[index] for index in pending_indexes)
        task_index = len(task_records)
        identity_path = self.__getIdentityPath()
        task_id = fallback_task_id(description, identity_path, task_index)
        existing_ids = {
            self.__resolveRecordIdentity(record, index, identity_path)
            for index, record in enumerate(task_records)
        }
        reserved_ids = set(self.__pendingNewTaskIds.values())
        if task_id in existing_ids or task_id in reserved_ids:
            raise AmbiguousTaskIdentityError("New task ID conflicts with an existing task")
        default_task["id"] = task_id
        task = self.createTaskFromDict(default_task, task_index, task_id, identity_path)
        task_records.append(default_task)
        self.__pendingNewTasks[task_index] = default_task
        self.__pendingNewTaskIds[task_index] = task_id

        return task

    def discardPendingTaskReservations(self) -> None:
        """Drop unpersisted new-task positions after an abandoned operation."""
        self.__pendingNewTasks.clear()
        self.__pendingNewTaskIds.clear()

    def getTaskMetadata(self, task: ITaskModel) -> str:
        """
        Gets the metadata of a task.

        This method gets the metadata of a task in string format.

        Params:
            task: The task to get the metadata from.
        """
        return dict(
            description=task.getDescription(),
            context=task.getContext(),
            start=task.getStart().as_int(),
            due=task.getDue(),
            severity=task.getSeverity(),
            totalCost=task.getTotalCost().as_pomodoros(),
            investedEffort=task.getInvestedEffort().as_pomodoros(),
            status=task.getStatus(),
            calm="True" if task.getCalm() else "False"
        ).__str__()

    def registerTaskListUpdatedCallback(self, callback: Callable[[], None]) -> None:
        self.onTaskListUpdatedCallbacks.append(callback)
        pass

    def compare(self, list_a: list[ITaskModel], list_b: list[ITaskModel]) -> bool:
        if len(list_a) != len(list_b):
            return False
        for i in range(len(list_a)):
            if list_a[i] != list_b[i]:
                return False
        return True

    def _exportJson(self) -> bytearray:
        jsonData = self.taskJsonProvider.getJson()
        jsonStr = json.dumps(jsonData, indent=4)
        return bytearray(jsonStr, "utf-8")

    def exportTasks(self, selectedFormat: str) -> bytearray:
        supportedFormats: dict[str, Callable[[], bytearray]] = {
            "json": self._exportJson,
        }

        return supportedFormats[selectedFormat]()

    def _importJson(self) -> None:
        imported_json = self.fileBroker.readFileContentJson(FileRegistry.LAST_RECEIVED_FILE)
        imported_records = self.__getTaskRecords(imported_json)
        identity_path = self.__getIdentityPath()
        for index, record in enumerate(imported_records):
            self.__resolveRecordIdentity(record, index, identity_path)
        committed = self.taskJsonProvider.updateJson(lambda _current: deepcopy(imported_json))
        self.dict_task_list = deepcopy(committed)

    def importTasks(self, selectedFormat: str) -> None:
        supportedFormats: dict[str, Callable[[], None]] = {
            "json": self._importJson,
        }

        supportedFormats[selectedFormat]()
