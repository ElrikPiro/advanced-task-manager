import datetime

from typing import List, Tuple
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel

class RemainingEffortHeuristic(IHeuristic):

    def __init__(self, pomodorosPerDay: float, desiredH : float):
        self.pomodorosPerDay = pomodorosPerDay
        self.desiredH = desiredH

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        retval = [(task, self.evaluate(task)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

        #let desiredRemainingCost = (dr) => (dr * d * p) / (p*s*w + dr)
		#let remainingWork = (dr) => r - desiredRemainingCost(dr)

    def evaluate(self, task: ITaskModel) -> float:
        p = self.pomodorosPerDay
        w = 1
        s = task.getSeverity()
        r = task.getTotalCost() - task.getInvestedEffort()
        d = task.calculateRemainingTime()

        dr = self.desiredH

        return r - ((dr * d * p) / (p*s*w + dr))