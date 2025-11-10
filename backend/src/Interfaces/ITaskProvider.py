from abc import ABC, abstractmethod
from typing import Callable, List

from .ITaskModel import ITaskModel


class ITaskProvider(ABC):

    @abstractmethod
    def getTaskList(self) -> List[ITaskModel]:
        pass

    @abstractmethod
    def getTaskListAttribute(self, string: str) -> str:
        pass

    @abstractmethod
    def saveTask(self, task: ITaskModel) -> None:
        pass

    @abstractmethod
    def createDefaultTask(self, description: str) -> ITaskModel:
        pass

    @abstractmethod
    def getTaskMetadata(self, task: ITaskModel) -> str:
        pass

    @abstractmethod
    def registerTaskListUpdatedCallback(self, callback: Callable[[], None]) -> None:
        pass

    @abstractmethod
    def compare(self, listA: list[ITaskModel], listB: list[ITaskModel]) -> bool:
        pass

    @abstractmethod
    def exportTasks(self, selectedFormat: str) -> bytearray:
        pass

    @abstractmethod
    def importTasks(self, selectedFormat: str) -> None:
        pass

    @abstractmethod
    def dispose(self) -> None:
        pass
