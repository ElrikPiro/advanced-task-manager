from abc import ABC, abstractmethod
from typing import List

from src.Interfaces.ITaskModel import ITaskModel


class ITaskProvider(ABC):

    @abstractmethod
    def getTaskList(self) -> List[ITaskModel]:
        pass

    @abstractmethod
    def getTaskListAttribute(self, string: str) -> str:
        pass

    @abstractmethod
    def saveTask(self, task: ITaskModel):
        pass

    @abstractmethod
    def createDefaultTask(self, description: str) -> ITaskModel:
        pass

    @abstractmethod
    def getTaskMetadata(self, task: ITaskModel) -> str:
        pass

    @abstractmethod
    def registerTaskListUpdatedCallback(self, callback):
        pass

    @abstractmethod
    def compare(self, listA: list[ITaskModel], listB: list[ITaskModel]) -> bool:
        pass

    @abstractmethod
    def exportTasks(self, selectedFormat: str) -> bytearray:
        pass

    @abstractmethod
    def importTasks(self, selectedFormat: str):
        pass

    @abstractmethod
    def dispose(self):
        pass
