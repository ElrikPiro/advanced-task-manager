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