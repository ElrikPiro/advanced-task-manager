import datetime
from math import ceil
from ..wrappers.TimeManagement import TimePoint, TimeAmount

from ..Interfaces.ITaskModel import ITaskModel
from .TaskModel import TaskModel

class ObsidianTaskModel(TaskModel):
    def __init__(self, description: str, context: str, start: int, due: int, severity: float, totalCost: float, investedEffort: float, status: str, file: str, line: int, calm : str):
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

    # Overrided
    def getDescription(self) -> str:
        slash = "/"
        dot = "."
        return f"{self._description} @ '{self._file.split(slash).pop().split(dot)[0]}:{self._line}'"
    
    def __eq__(self, other : ITaskModel):
        return self.getDescription() == other.getDescription() and self.getContext() == other.getContext() and self.getStart() == other.getStart() and self.getDue() == other.getDue() and self.getSeverity() == other.getSeverity() and self.getTotalCost().as_pomodoros() == other.getTotalCost().as_pomodoros() and self.getInvestedEffort().as_pomodoros() == other.getInvestedEffort().as_pomodoros() and self.getStatus() == other.getStatus() and self.getFile() == other.getFile() and self.getLine() == other.getLine() and self.getCalm() == other.getCalm()

    # Class methods
    def getFile(self) -> str:
        return self._file
    
    def getLine(self) -> int:
        return self._line
    
    def setFile(self, file: str):
        self._file = file

    def setLine(self, line: int):
        self._line = line