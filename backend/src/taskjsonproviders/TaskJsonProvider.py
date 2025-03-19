# class interface

from typing import List

from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry


class TaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker):
        self.fileBroker = fileBroker

    def getJson(self) -> dict:
        """
        Reads the tasks json file and injects tasks for projects without any task assigned.

        Returns:
            dict: The tasks json.
        """
        taskJson = self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        taskJson = self.__injectOpenProjectTasks(taskJson)
        return taskJson

    def saveJson(self, json: dict):
        self.fileBroker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, json)

    def __injectOpenProjectTasks(self, taskJson: dict) -> dict:
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

            if task.get("project", None) is None or taskProject in projectsFound or task.get("status", "x") != " ":
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
        return taskJson
