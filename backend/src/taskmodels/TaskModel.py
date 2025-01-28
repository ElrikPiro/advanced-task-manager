import datetime
from math import ceil
from ..wrappers.TimeManagement import TimePoint, TimeAmount
from ..Interfaces.ITaskModel import ITaskModel

class TaskModel(ITaskModel):
    def __init__(self, description: str, context: str, start: int, due: int, severity: float, totalCost: float, investedEffort: float, status: str, calm : str, index : int):
        self._description : str = description
        self._context : str = context
        self._start : int = int(start)
        self._due : int = int(due)
        self._severity : float = float(severity)
        self._totalCost : float = float(totalCost)
        self._investedEffort : float = float(investedEffort)
        self._status : str = status
        self._calm : bool = True if calm.upper().startswith("TRUE") else False
        self._index : int = index

    def getDescription(self) -> str:
        return f"{self._description}"

    def getContext(self) -> str:
        return self._context

    def getStart(self) -> TimePoint:
        return TimePoint(datetime.datetime.fromtimestamp(self._start / 1e3))

    def getDue(self) -> TimePoint:
        return TimePoint(datetime.datetime.fromtimestamp(self._due / 1e3))

    def getSeverity(self) -> float:
        return self._severity

    def getTotalCost(self) -> TimeAmount:
        return TimeAmount(f"{self._totalCost}p")

    def getInvestedEffort(self) -> TimeAmount:
        return TimeAmount(f"{self._investedEffort}p")

    def getStatus(self) -> str:
        return self._status
    
    def getCalm(self) -> bool:
        return self._calm

    def setDescription(self, description: str):
        self._description = description

    def setContext(self, context: str):
        self._context = context

    def setStart(self, start: TimePoint):
        self._start = start.as_int()

    def setDue(self, due: int):
        self._due = due

    def setSeverity(self, severity: float):
        self._severity = severity

    def setTotalCost(self, totalCost: TimeAmount):
        self._totalCost = totalCost.as_pomodoros()

    def setInvestedEffort(self, investedEffort: float):
        self._investedEffort = investedEffort

    def setStatus(self, status: str):
        self._status = status

    def setCalm(self, calm: bool):
        self._calm = calm

    def calculateRemainingTime(self) -> int:
        dueDate = self.getDue().as_int()

        currentDate = TimePoint.now().as_int()
        d = (dueDate - currentDate) / (datetime.timedelta(days=1).total_seconds() * 1000)
        d = max(0, d)
        d = ceil(d)
        return d + 0.5
    
    def __eq__(self, other : ITaskModel):
        return self._index == other._index