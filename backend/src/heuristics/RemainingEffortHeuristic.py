from typing import List, Tuple
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimeAmount


class RemainingEffortHeuristic(IHeuristic):

    def __init__(self, dedication: TimeAmount, desiredH: float):
        self.dedication = dedication
        self.desiredH = desiredH

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pomodorosPerDay = self.dedication.as_pomodoros()
        retval = [(task, self.fastEvaluate(task, pomodorosPerDay)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def evaluate(self, task: ITaskModel) -> float:
        p = self.dedication.as_pomodoros()
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
