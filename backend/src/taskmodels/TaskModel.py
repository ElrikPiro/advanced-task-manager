import datetime
from math import ceil

from ..Interfaces.ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimePoint, TimeAmount

class TaskModel(ITaskModel):
    def __init__(self, description: str, context: str, start: TimePoint, due: TimePoint, severity: float, totalCost: TimeAmount, investedEffort: TimeAmount, status: str, calm : str, index : int):
        self._description : str = description
        self._context : str = context
        self._start : TimePoint = start
        self._due : TimePoint = due
        self._severity : float = float(severity)
        self._totalCost : TimeAmount = totalCost
        self._investedEffort : TimeAmount = investedEffort
        self._status : str = status
        self._calm : bool = True if calm.upper().startswith("TRUE") else False
        self._index : int = index

    def getDescription(self) -> str:
        return f"{self._description}"

    def getContext(self) -> str:
        return self._context

    def getStart(self) -> TimePoint:
        return self._start

    def getDue(self) -> TimePoint:
        return self._due

    def getSeverity(self) -> float:
        return self._severity

    def getTotalCost(self) -> TimeAmount:
        return self._totalCost

    def getInvestedEffort(self) -> TimeAmount:
        return self._investedEffort

    def getStatus(self) -> str:
        return self._status
    
    def getCalm(self) -> bool:
        return self._calm

    def setDescription(self, description: str):
        self._description = description

    def setContext(self, context: str):
        self._context = context

    def setStart(self, start: TimePoint):
        self._start = start

    def setDue(self, due: TimePoint):
        self._due = due

    def setSeverity(self, severity: float):
        self._severity = severity

    def setTotalCost(self, totalCost: TimeAmount):
        self._totalCost = totalCost

    def setInvestedEffort(self, investedEffort: TimeAmount):
        self._investedEffort = investedEffort

    def setStatus(self, status: str):
        self._status = status

    def setCalm(self, calm: bool):
        self._calm = calm

    def calculateRemainingTime(self) -> int:
        dueDate = self.getDue().datetime_representation.timestamp() * 1000

        currentDate = datetime.datetime.now().timestamp() * 1000
        d = (dueDate - currentDate) / (datetime.timedelta(days=1).total_seconds() * 1000)
        d = max(0, d)
        d = ceil(d)
        return d + 0.5
    
    def __eq__(self, other : ITaskModel):
        return self._index == other._index
