import datetime

from typing import List, Tuple
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel

class SlackHeuristic(IHeuristic):

    def __init__(self, pomodorosPerDay: float):
        self.pomodorosPerDay = pomodorosPerDay

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        retval = [(task, self.evaluate(task)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def evaluate(self, task: ITaskModel) -> float:
        p = self.pomodorosPerDay
        w = 1
        s = task.getSeverity()
        r = task.getTotalCost() - task.getInvestedEffort()
        d = task.calculateRemainingTime()

        try:
            h = (p * w * s * r) / (p * d - r)
            return round(h, 2) if h > 0 else 100
        except ZeroDivisionError:
            return 100