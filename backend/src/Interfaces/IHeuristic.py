from abc import ABC, abstractmethod
from typing import List, Tuple
from .ITaskModel import ITaskModel

class IHeuristic(ABC):

    @abstractmethod
    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pass

    @abstractmethod
    def evaluate(self, task: ITaskModel) -> float:
        pass

    @abstractmethod
    def getComment(self, task: ITaskModel) -> str:
        pass
