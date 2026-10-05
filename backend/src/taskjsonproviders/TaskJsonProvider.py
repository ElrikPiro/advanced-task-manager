# class interface

from copy import deepcopy
from typing import Any, Callable, List, cast

from src.Utils import TaskJsonType

from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry
from ..taskmodels.TaskIdentity import fallback_task_id, validate_task_id
from ..taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError
from ..MutationCoordinator import MutationCoordinator


class ConfirmedTaskJsonRefreshError(RuntimeError):
    """A JSON task update was confirmed but its returned data was unusable."""

    effects_state = "unknown"


class TaskJsonProvider(ITaskJsonProvider):

    def __init__(
        self,
        fileBroker: IFileBroker,
        mutation_coordinator: MutationCoordinator | None = None,
    ):
        self.fileBroker = fileBroker
        self.mutation_coordinator = mutation_coordinator
        if self.mutation_coordinator is None:
            inherited_coordinator = getattr(fileBroker, "mutation_coordinator", None)
            if isinstance(inherited_coordinator, MutationCoordinator):
                self.mutation_coordinator = inherited_coordinator

    def getJson(self) -> TaskJsonType:
        """
        Reads and parses the tasks JSON without reconciling or writing discoveries.

        Returns:
            dict: The tasks json.
        """
        taskJson: TaskJsonType = self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        self.__validateDeclaredTaskIds(taskJson)
        return deepcopy(taskJson)

    def discover(self) -> TaskJsonType:
        """Persist the default next action for every uncovered open project."""
        if self.mutation_coordinator is not None:
            return self.mutation_coordinator.run_or_inline(self.__discover)
        return self.__discover()

    def __discover(self) -> TaskJsonType:
        today = str(TimePoint.today().as_int())
        identity_path = self.fileBroker.getFilePath(FileRegistry.STANDALONE_TASKS_JSON)

        def reconcile(current: TaskJsonType) -> TaskJsonType:
            return self.__injectOpenProjectTasks(current, today, identity_path)

        return self.updateJson(reconcile)

    def updateJson(self, updater: Callable[[TaskJsonType], TaskJsonType]) -> TaskJsonType:
        """Apply a pure mutation to the latest file contents under the broker lock."""
        def validated_update(current: dict[str, Any]) -> dict[str, Any]:
            candidate = updater(cast(TaskJsonType, deepcopy(current)))
            self.__validateDeclaredTaskIds(candidate)
            return cast(dict[str, Any], candidate)

        committed = self.fileBroker.updateFileContentJson(
            FileRegistry.STANDALONE_TASKS_JSON,
            validated_update,
        )
        try:
            self.__validateDeclaredTaskIds(cast(TaskJsonType, committed))
        except Exception as error:
            raise ConfirmedTaskJsonRefreshError("Confirmed task JSON could not be validated") from error
        return cast(TaskJsonType, deepcopy(committed))

    def saveJson(self, json: TaskJsonType) -> None:
        self.__validateDeclaredTaskIds(json)
        self.fileBroker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, json)

    def __validateDeclaredTaskIds(self, taskJson: TaskJsonType) -> None:
        tasks = taskJson.get("tasks", [])
        if not isinstance(tasks, list):
            raise TypeError("Task data attribute 'tasks' must be a list")
        for task in tasks:
            if isinstance(task, dict) and "id" in task:
                validate_task_id(task["id"])

    def __injectOpenProjectTasks(
        self,
        taskJson: TaskJsonType,
        today: str,
        identity_path: str,
    ) -> TaskJsonType:
        """
        Queries the json to find projects without any task assigned and adds a task to the task list with that project assigned.

        Params:
            taskJson: The json to be queried.

        Returns:
            dict: The json with the tasks injected.
        """
        projects = taskJson.get("projects", [])
        tasks = taskJson.get("tasks", [])
        projectsFound: List[str] = []

        for task in tasks:
            taskProject = task.get("project", None)

            if not isinstance(taskProject, str) or taskProject in projectsFound or task.get("status", "x") != " ":
                continue

            projectsFound.append(taskProject)

        for project in projects:
            if project["name"] not in projectsFound and project["status"] == "open":
                task = {
                    "description": "Define next action",
                    "project": project["name"],
                    "context": "alert",
                    "start": today,
                    "due": today,
                    "severity": "1",
                    "totalCost": "1",
                    "investedEffort": "0",
                    "status": " ",
                    "calm": "False"
                }
                task_id = fallback_task_id(
                    task["description"],
                    identity_path,
                    len(tasks),
                )
                existing_ids = {
                    validate_task_id(record["id"]) if "id" in record else fallback_task_id(
                        record["description"],
                        identity_path,
                        index,
                    )
                    for index, record in enumerate(tasks)
                }
                if task_id in existing_ids:
                    raise AmbiguousTaskIdentityError("New task ID conflicts with an existing task")
                task["id"] = task_id
                tasks.append(task)
        if tasks and "tasks" not in taskJson:
            taskJson["tasks"] = tasks
        return taskJson
