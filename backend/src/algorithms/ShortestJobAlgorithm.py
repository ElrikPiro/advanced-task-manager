from typing import List

from src.Interfaces.ITaskModel import ITaskModel
from src.algorithms.Interfaces.IAlgorithm import IAlgorithm


class ShortestJobAlgorithm(IAlgorithm):
    """
    Shortest Job First (SJF) algorithm for task scheduling.

    This algorithm prioritizes tasks based on their execution time.
    Tasks with the shortest execution times are given higher priority.

    The algorithm consists of the following steps:
    1. Sort tasks in ascending order of their execution times.
    """

    def __init__(self):
        pass

    def apply(self, taskList: List[ITaskModel]) -> List[ITaskModel]:
        """
        Execute the SJF algorithm with the given parameters.
        Args:
            taskList (list): The list of tasks to be processed by the algorithm.
        Returns:
            list: The list of tasks after applying the algorithm.
        """

        sorted_tasks = sorted(taskList, key=lambda task: task.getTotalCost().as_pomodoros())

        self.description = "Shortest Job First (SJF) Algorithm"
        self.description += f" \n    - {len(sorted_tasks)} tasks sorted by execution time"

        return sorted_tasks

    def getDescription(self) -> str:
        return "This algorithm prioritizes tasks based on their execution time."
