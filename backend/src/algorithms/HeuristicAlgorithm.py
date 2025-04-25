from typing import List

from src.Interfaces import IHeuristic
from src.Interfaces.ITaskModel import ITaskModel
from src.algorithms.Interfaces.IAlgorithm import IAlgorithm


class HeuristicAlgorithm(IAlgorithm):
    """
    Algorithm that uses a heuristic to sort tasks.
    """

    def __init__(self, heuristic: IHeuristic, description: str):
        self.heuristic = heuristic
        self.description = description

    def apply(self, taskList: List[ITaskModel]) -> List[ITaskModel]:
        """
        Apply the heuristic's sort method to the task list.

        Args:
            taskList (List[ITaskModel]): The list of tasks to be processed.

        Returns:
            List[ITaskModel]: The sorted list of tasks.
        """
        sorted_tasks_with_values = self.heuristic.sort(taskList)
        sorted_tasks = [task for task, _ in sorted_tasks_with_values]
        return sorted_tasks

    def getDescription(self) -> str:
        return self.description
