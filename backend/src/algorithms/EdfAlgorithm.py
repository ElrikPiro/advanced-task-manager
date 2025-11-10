from typing import List

from src.Interfaces.ITaskModel import ITaskModel
from src.algorithms.Interfaces.IAlgorithm import IAlgorithm


class EdfAlgorithm(IAlgorithm):
    """
    Earliest Due Date (EDF) algorithm for task scheduling.

    This algorithm prioritizes tasks based on their due dates.
    Tasks with the earliest due dates are given higher priority.
    The algorithm consists of the following steps:
    1. Filter tasks based on their due dates.
    2. Sort tasks in ascending order of their due dates.
    3. Return the sorted list of tasks.
    """

    def __init__(self) -> None:
        pass

    def apply(self, taskList: List[ITaskModel]) -> List[ITaskModel]:
        """
        Execute the EDF algorithm with the given parameters.
        Args:
            taskList (list): The list of tasks to be processed by the algorithm.
        Returns:
            list: The list of tasks after applying the algorithm.
        """

        sorted_tasks = sorted(taskList, key=lambda task: task.getDue().as_int())
        # update description to tell the user which algorithm was used
        self.description = "Earliest Due Date (EDF) Algorithm"
        # and how many tasks were sorted
        self.description += f" \n    - {len(sorted_tasks)} tasks sorted by due date"
        # and when is the earliest deadline
        if sorted_tasks:
            self.description += f" \n    - Earliest deadline: {sorted_tasks[0].getDue()}"

        return sorted_tasks

    def getDescription(self) -> str:
        return "This algorithm prioritizes tasks based on their due dates."
