from abc import ABC, abstractmethod
from typing import List
from .ITaskModel import ITaskModel


class IFilter(ABC):

    @abstractmethod
    def filter(self, tasks: List[ITaskModel]) -> List[ITaskModel]:
        pass

    @abstractmethod
    def getDescription(self) -> str:
        pass
