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
        dueDate = task.getDue()

        currentDate = datetime.datetime.now().timestamp() * 1000
        d = (dueDate - currentDate) / (datetime.timedelta(days=1).total_seconds() * 1000)
        d = max(0, d)

        return round((p * w * s * r) / (p * d - r), 2)