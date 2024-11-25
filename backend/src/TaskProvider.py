import datetime
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .TaskModel import TaskModel
from typing import List
import json

class TaskProvider(ITaskProvider):

    def __init__(self, task_json_provider : ITaskJsonProvider):
        self.taskJsonProvider = task_json_provider
        self.dict_task_list = self.taskJsonProvider.getJson()
        self.taskJsonProvider.onTaskListUpdatedCallbacks = []

    def getTaskList(self) -> List[ITaskModel]:
        task_list = []
        index = 0
        for task in self.dict_task_list["tasks"]:
            task_list.append(self.createTaskFromDict(task, index))
            index += 1
        return task_list

    def createTaskFromDict(self, dict_task : dict, index : int) -> ITaskModel:
        return TaskModel(index=index, description=dict_task["description"], context=dict_task["context"], start=dict_task["start"], due=dict_task["due"], severity=dict_task["severity"], totalCost=dict_task["totalCost"], investedEffort=dict_task["investedEffort"], status=dict_task["status"], calm=dict_task["calm"])

    def getTaskListAttribute(self, string: str) -> str:
        try:
            return self.dict_task_list[string]
        except Exception:
            return ""

    def saveTask(self, task: ITaskModel):
        # edit the dictionary to be saved
        task_list = self.getTaskList()
        for index in range(len(task_list)):
            if task_list[index] == task:
                self.dict_task_list["tasks"][index] = dict(
                    description=task.getDescription(), 
                    context=task.getContext(), 
                    start=task.getStart(), 
                    due=task.getDue(), 
                    severity=task.getSeverity(), 
                    totalCost=task.getTotalCost(), 
                    investedEffort=task.getInvestedEffort(), 
                    status=task.getStatus(), 
                    calm="True" if task.getCalm() else "False"
                )
                break
        
        self.taskJsonProvider.saveJson(self.dict_task_list)
        for callback in self.taskJsonProvider.onTaskListUpdatedCallbacks:
            callback()

    def createDefaultTask(self, description: str) -> ITaskModel:
        starts = int(datetime.datetime.now().timestamp() * 1e3)
        due = int(datetime.datetime.today().timestamp() * 1e3)
        starts = starts - starts % 60000
        due = due - due % 60000
        
        severity = 1.0
        invested = 0.0
        status = " "
        calm = "False"
        
        default_task = dict(
            description=description, 
            context="workstation", 
            start=starts, 
            due=due, 
            severity=severity, 
            totalCost=1.0, 
            investedEffort=invested, 
            status=status, 
            calm=calm
        )

        task = self.createTaskFromDict(default_task, len(self.dict_task_list["tasks"]))
        self.dict_task_list["tasks"].append(default_task)
        self.saveTask(task)

        return task

    def getTaskMetadata(self, task: ITaskModel) -> str:
        # return as stringyfied dictionary
        return dict(
            description=task.getDescription(), 
            context=task.getContext(), 
            start=task.getStart(), 
            due=task.getDue(), 
            severity=task.getSeverity(), 
            totalCost=task.getTotalCost(), 
            investedEffort=task.getInvestedEffort(), 
            status=task.getStatus(), 
            calm="True" if task.getCalm() else "False"
        ).__str__()

    def registerTaskListUpdatedCallback(self, callback):
        # self.taskJsonProvider.onTaskListUpdatedCallbacks.append(callback)
        pass

    def compare(self, list_a : list[ITaskModel], list_b : list[ITaskModel]) -> bool:
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

    def exportTasks(self, selectedFormat : str) -> bytearray:
        supportedFormats : dict = {
            "json": self._exportJson,
        }

        return supportedFormats[selectedFormat]()