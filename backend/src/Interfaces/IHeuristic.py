from abc import ABC, abstractmethod
from typing import List, Tuple
from .ITaskModel import ITaskModel


class IHeuristic(ABC):

    @abstractmethod
    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        """
        Sorts a list of tasks based on the heuristic evaluation.
        Returns a list of tuples (task, value) sorted in a logical order.
        """
        pass

    @abstractmethod
    def evaluate(self, task: ITaskModel) -> float:
        """
        Evaluates the heuristic for a given task.
        Returns a float value representing the heuristic's evaluation.
        """
        pass

    @abstractmethod
    def getComment(self, task: ITaskModel) -> str:
        """
        Returns a string with the heuristic's comment for the task.
        This is used for displaying the heuristic value in the UI.
        """
        pass

    @abstractmethod
    def getDescription(self) -> str:
        pass
