from typing import List, Tuple
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimeAmount


class SlackHeuristic(IHeuristic):

    def __init__(self, dedication: TimeAmount, daysOffset: int = 0):
        self.dedication = dedication
        self.daysOffset = daysOffset

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pomodorosPerDay = self.dedication.as_pomodoros()
        retval = [(task, self.fastEvaluate(task, pomodorosPerDay)) for task in tasks]
        retval.sort(key=lambda x: x[1], reverse=True)
        return retval

    def fastEvaluate(self, task: ITaskModel, pomodorosPerDay: float) -> float:
        p = pomodorosPerDay
        w = 1
        s = task.getSeverity()
        r = task.getTotalCost().as_pomodoros()
        d = task.calculateRemainingTime().as_days() - self.daysOffset

        if d < 1:
            return 100

        try:
            h = (p * w * s * r) / (p * d - r)
            return round(h, 2) if h > 0 else 100
        except ZeroDivisionError:
            return 100

    def evaluate(self, task: ITaskModel) -> float:
        p = self.dedication.as_pomodoros()
        return self.fastEvaluate(task, p)

    def getComment(self, task: ITaskModel) -> str:
        return f"{round(self.evaluate(task), 2)}"
