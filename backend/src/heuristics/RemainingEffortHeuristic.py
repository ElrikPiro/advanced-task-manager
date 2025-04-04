from typing import List, Tuple
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskProvider import ITaskProvider
from src.wrappers.TimeManagement import TimeAmount


class RemainingEffortHeuristic(IHeuristic):

    def __init__(self, pomodorosPerDayProvider: ITaskProvider, desiredH: float):
        self.pomodorosPerDayProvider = pomodorosPerDayProvider
        self.desiredH = desiredH

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pomodorosPerDay = float(self.pomodorosPerDayProvider.getTaskListAttribute("pomodoros_per_day"))
        retval = [(task, self.fastEvaluate(task, pomodorosPerDay)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def evaluate(self, task: ITaskModel) -> float:
        p = float(self.pomodorosPerDayProvider.getTaskListAttribute("pomodoros_per_day"))
        return self.fastEvaluate(task, p)

    def fastEvaluate(self, task: ITaskModel, pomodorosPerDay: float) -> float:
        p = pomodorosPerDay
        w = 1
        s = task.getSeverity()
        r = task.getTotalCost().as_pomodoros()
        d = task.calculateRemainingTime().as_days()

        dr = self.desiredH

        return r - ((dr * d * p) / (p * s * w + dr))

    def getComment(self, task: ITaskModel) -> str:
        remaining_effort = self.evaluate(task)
        time_amount = TimeAmount(str(remaining_effort) + "p")
        return str(time_amount)
