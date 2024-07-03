from .Interfaces.ITaskModel import ITaskModel

class ObsidianTaskModel(ITaskModel):
    def __init__(self, description: str, context: str, start: int, due: int, severity: float, totalCost: float, investedEffort: float, status: str, file: str, line: int):
        self._description = description
        self._context = context
        self._start = start
        self._due = due
        self._severity = severity
        self._totalCost = totalCost
        self._investedEffort = investedEffort
        self._status = status
        self._file = file
        self._line = line

    def getDescription(self) -> str:
        return self._description

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

    def setFile(self, file: str):
        self._file = file

    def setLine(self, line: int):
        self._line = line