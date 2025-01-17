import datetime
from math import ceil

from ..Interfaces.ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimePoint, TimeAmount

class ObsidianTaskModel(ITaskModel):
    def __init__(self, description: str, context: str, start: TimePoint, due: TimePoint, severity: float, totalCost: TimeAmount, investedEffort: TimeAmount, status: str, file: str, line: int, calm : str):
        self._description : str = description
        self._context : str = context
        self._start : TimePoint = start
        self._due : TimePoint = due
        self._severity : float = float(severity)
        self._totalCost : TimeAmount = totalCost
        self._investedEffort : TimeAmount = investedEffort
        self._status : str = status
        self._file : str = file
        self._line : int = int(line)
        self._calm : bool = True if calm.upper().startswith("TRUE") else False

    def getDescription(self) -> str:
        slash = "/"
        dot = "."
        return f"{self._description} @ '{self._file.split(slash).pop().split(dot)[0]}:{self._line}'"

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
    
    def getFile(self) -> str:
        return self._file
    
    def getLine(self) -> int:
        return self._line
    
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

    def setFile(self, file: str):
        self._file = file

    def setLine(self, line: int):
        self._line = line

    def calculateRemainingTime(self) -> int:
        dueDate = self.getDue().datetime_representation.timestamp() * 1000

        currentDate = datetime.datetime.now().timestamp() * 1000
        d = (dueDate - currentDate) / (datetime.timedelta(days=1).total_seconds() * 1000)
        d = max(0, d)
        d = ceil(d)
        return d + 0.5
    
    def __eq__(self, other : ITaskModel):
        return self.getDescription() == other.getDescription() and self.getContext() == other.getContext() and self.getStart() == other.getStart() and self.getDue() == other.getDue() and self.getSeverity() == other.getSeverity() and self.getTotalCost() == other.getTotalCost() and self.getInvestedEffort() == other.getInvestedEffort() and self.getStatus() == other.getStatus() and self.getFile() == other.getFile() and self.getLine() == other.getLine() and self.getCalm() == other.getCalm()
