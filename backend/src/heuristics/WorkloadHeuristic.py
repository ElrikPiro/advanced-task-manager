from typing import List, Tuple
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel


class WorkloadHeuristic(IHeuristic):

    def __init__(self) -> None:
        pass

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        retval = [(task, self.fastEvaluate(task)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def fastEvaluate(self, task: ITaskModel, pomodorosPerDay: float | None = None) -> float:
        r = task.getTotalCost().as_pomodoros()
        d = task.calculateRemainingTime().as_days()

        if d < 1:
            return r

        try:
            h = r / d
            return round(h, 2) if h > 0 else r
        except ZeroDivisionError:
            return r

    def evaluate(self, task: ITaskModel) -> float:
        return self.fastEvaluate(task)

    def getComment(self, task: ITaskModel) -> str:
        return f"{round(self.evaluate(task), 2)}"
        
    def getDescription(self) -> str:
        """
        Returns a description of the heuristic.
        """
        return "Workload heuristic: calculates remaining cost divided by remaining days"
