import datetime

from typing import List, Tuple
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskProvider import ITaskProvider

class DaysToThresholdHeuristic(IHeuristic):

    def __init__(self, pomodorosPerDayProvider: ITaskProvider, threshold: float):
        self.pomodorosPerDayProvider = pomodorosPerDayProvider
        self.threshold = threshold

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pomodorosPerDay = float(self.pomodorosPerDayProvider.getTaskListAttribute("pomodoros_per_day"))
        retval = [(task, self.fastEvaluate(task, pomodorosPerDay)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def fastEvaluate(self, task: ITaskModel, pomodorosPerDay : float) -> float:
        p = pomodorosPerDay
        w = 1
        s = task.getSeverity()
        r = task.getTotalCost()
        d = task.calculateRemainingTime()
        h = self.threshold

        return d - (r * (p*s*w + h)) / (h*p)

    def evaluate(self, task: ITaskModel) -> float:
        p = float(self.pomodorosPerDayProvider.getTaskListAttribute("pomodoros_per_day"))
        return self.fastEvaluate(task, p)

    def getComment(self) -> str:
        return "This heuristic calculates the number of days remaining until the task reaches the threshold."
