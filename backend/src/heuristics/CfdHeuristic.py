from typing import List, Tuple

from src.wrappers.TimeManagement import TimeAmount, TimePoint
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel


class CfdHeuristic(IHeuristic):

    def __init__(self, dedication: TimeAmount, daysOffset: int = 0):
        self.dedication = dedication
        self.daysOffset = daysOffset

    def sort(self, tasks: List[ITaskModel]) -> List[Tuple[ITaskModel, float]]:
        pomodorosPerDay = self.dedication.as_pomodoros()
        retval = [(task, self.fastEvaluate(task, pomodorosPerDay)) for task in tasks]
        retval.sort(key=lambda x: x[1])
        return retval

    def fastEvaluate(self, task: ITaskModel, pomodorosPerDay: float) -> float:
        ppd = pomodorosPerDay
        nice = task.getSeverity()
        remaining = task.getTotalCost().as_pomodoros()
        daysActive = TimeAmount(f"{int(TimePoint.today().timestamp) - int(task.getStart().timestamp)}s").as_days()
        period = TimeAmount(f"{int(nice * remaining / ppd)}p").as_pomodoros()
        divisor = 1 + daysActive / period

        return task.getInvestedEffort().as_pomodoros() / divisor

    def evaluate(self, task: ITaskModel) -> float:
        p = self.dedication.as_pomodoros()
        return self.fastEvaluate(task, p)

    def getComment(self, task: ITaskModel) -> str:
        return f"{round(self.evaluate(task), 2)}"
        
    def getDescription(self) -> str:
        """
        Returns a description of the heuristic.
        """
        return (
            "CFD (Cumulative Flow Diagram) Heuristic: Prioritizes tasks that are falling behind schedule. "
            "It computes a score by dividing the invested effort by a divisor that grows as the task ages "
            "relative to its expected completion period (severity * remaining_cost / daily_dedication). "
            "Tasks with lower scores—meaning less effort invested relative to how overdue they are—are "
            "prioritized first, surfacing neglected or under-progressed tasks."
        )
