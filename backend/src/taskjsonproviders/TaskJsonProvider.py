# class interface

from copy import deepcopy
from typing import List

from src.Utils import TaskJsonType

from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry


class TaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker):
        self.fileBroker = fileBroker

    def getJson(self) -> TaskJsonType:
        """
        Reads and parses the tasks JSON without reconciling or writing discoveries.

        Returns:
            dict: The tasks json.
        """
        taskJson: TaskJsonType = self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        return deepcopy(taskJson)

    def discover(self) -> TaskJsonType:
        """Persist the default next action for every uncovered open project."""
        taskJson = self.getJson()
        original = deepcopy(taskJson)
        reconciled = self.__injectOpenProjectTasks(taskJson)
        if reconciled != original:
            self.saveJson(reconciled)
        return reconciled

    def saveJson(self, json: TaskJsonType) -> None:
        self.fileBroker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, json)

    def __injectOpenProjectTasks(self, taskJson: TaskJsonType) -> TaskJsonType:
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
                tasks.append({
                    "description": "Define next action",
                    "project": project["name"],
                    "context": "alert",
                    "start": str(TimePoint.today().as_int()),
                    "due": str(TimePoint.today().as_int()),
                    "severity": "1",
                    "totalCost": "1",
                    "investedEffort": "0",
                    "status": " ",
                    "calm": "False"
                })
        if tasks and "tasks" not in taskJson:
            taskJson["tasks"] = tasks
        return taskJson
