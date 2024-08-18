from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .TaskModel import TaskModel
from typing import List

class TaskProvider(ITaskProvider):

    def __init__(self, taskJsonProvider : ITaskJsonProvider):
        self.taskJsonProvider = taskJsonProvider
        pass

    def getTaskList(self) -> List[ITaskModel]:
        dictTaskList = self.taskJsonProvider.getJson()["tasks"]
        taskList = []
        index = 0
        for task in dictTaskList:
            taskList.append(self.createTaskFromDict(task), index)
            index += 1
        return taskList

    def createTaskFromDict(self, dictTask : dict, index : int) -> ITaskModel:
        return TaskModel(index=index, description=dictTask["description"], context=dictTask["context"], start=dictTask["start"], due=dictTask["due"], severity=dictTask["severity"], totalCost=dictTask["totalCost"], investedEffort=dictTask["investedEffort"], status=dictTask["status"], calm=dictTask["calm"])

    def getTaskListAttribute(self, string: str) -> str:
        return self.taskJsonProvider.getJson()[string]

    def saveTask(self, task: ITaskModel):
        # WIP
        pass

    def createDefaultTask(self, description: str) -> ITaskModel:
        pass

    def getTaskMetadata(self, task: ITaskModel) -> str:
        pass

    def registerTaskListUpdatedCallback(self, callback):
        pass

    def compare(self, listA : list[ITaskModel], listB : list[ITaskModel]) -> bool:
        pass