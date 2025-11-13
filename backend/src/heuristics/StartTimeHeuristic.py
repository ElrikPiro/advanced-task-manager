from src.Interfaces.IHeuristic import IHeuristic
from src.Interfaces.ITaskModel import ITaskModel


from typing import List, Tuple


class StartTimeHeuristic(IHeuristic):
    """
    Heuristic that returns the start time of a task.
    It's intended used is to create FIFO queues based on the start time of tasks.
    """

    def __init__(self) -> None:
        pass

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        retval = [(task, self.evaluate(task)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=False)
        return retval

    def evaluate(self, task: ITaskModel) -> float:
        return task.getStart().as_int() / 1000.0

    def getComment(self, task: ITaskModel) -> str:
        return str(task.getStart())
        
    def getDescription(self) -> str:
        """
        Returns a string with a description of the heuristic.
        Used for displaying information about the currently selected algorithm.
        """
        return "StartTime Heuristic: Orders tasks by their start time (FIFO)."
