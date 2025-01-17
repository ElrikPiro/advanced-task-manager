from typing import List, Tuple
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskProvider import ITaskProvider
from ..wrappers.TimeManagement import TimeAmount

class SlackHeuristic(IHeuristic):

    def __init__(self, pomodorosPerDayProvider: ITaskProvider):
        self.pomodorosPerDayProvider = pomodorosPerDayProvider

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pomodorosPerDay = float(self.pomodorosPerDayProvider.getTaskListAttribute("pomodoros_per_day"))
        retval = [(task, self.fastEvaluate(task, pomodorosPerDay)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def fastEvaluate(self, task: ITaskModel, pomodorosPerDay : float) -> float:
        p = pomodorosPerDay
        w = 1
        s = task.getSeverity()
        r = task.getTotalCost().int_representation
        d = task.calculateRemainingTime()

        try:
            h = (p * w * s * r) / (p * d - r)
            return round(h, 2) if h > 0 else 100
        except ZeroDivisionError:
            return 100

    def evaluate(self, task: ITaskModel) -> float:
        p = float(self.pomodorosPerDayProvider.getTaskListAttribute("pomodoros_per_day"))
        return self.fastEvaluate(task, p)

    def getComment(self, task: ITaskModel) -> str:
        return f"{round(self.evaluate(task), 2)}"
