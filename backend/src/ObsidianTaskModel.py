import datetime
from math import ceil

from .Interfaces.ITaskModel import ITaskModel

class ObsidianTaskModel(ITaskModel):
    def __init__(self, description: str, context: str, start: int, due: int, severity: float, totalCost: float, investedEffort: float, status: str, file: str, line: int, calm : str, vaultPath: str):
        self._description : str = description
        self._context : str = context
        self._start : int = int(start)
        self._due : int = int(due)
        self._severity : float = float(severity)
        self._totalCost : float = float(totalCost)
        self._investedEffort : float = float(investedEffort)
        self._status : str = status
        self._file : str = file
        self._line : int = int(line)
        self._calm : bool = True if calm.upper().startswith("TRUE") else False
        self._vaultPath : str = vaultPath

    def getDescription(self) -> str:
        slash = "/"
        dot = "."
        return f"{self._description} @ '{self._file.split(slash).pop().split(dot)[0]}:{self._line}'"

    def getContext(self) -> str:
        return self._context

    def getStart(self) -> int:
        return self._start

    def getDue(self) -> int:
        return self._due

    def getSeverity(self) -> float:
        return self._severity

    def getTotalCost(self) -> float:
        return self._totalCost

    def getInvestedEffort(self) -> float:
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

    def setStart(self, start: int):
        self._start = start

    def setDue(self, due: int):
        self._due = due

    def setSeverity(self, severity: float):
        self._severity = severity

    def setTotalCost(self, totalCost: float):
        self._totalCost = totalCost

    def setInvestedEffort(self, investedEffort: float):
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
        dueDate = self.getDue()

        currentDate = datetime.datetime.now().timestamp() * 1000
        d = (dueDate - currentDate) / (datetime.timedelta(days=1).total_seconds() * 1000)
        d = max(0, d)
        d = ceil(d)
        return d + 0.5
    
    def __eq__(self, other : ITaskModel):
        return self.getDescription() == other.getDescription() and self.getContext() == other.getContext() and self.getStart() == other.getStart() and self.getDue() == other.getDue() and self.getSeverity() == other.getSeverity() and self.getTotalCost() == other.getTotalCost() and self.getInvestedEffort() == other.getInvestedEffort() and self.getStatus() == other.getStatus() and self.getFile() == other.getFile() and self.getLine() == other.getLine()