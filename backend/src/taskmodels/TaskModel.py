import datetime
from math import ceil
from ..wrappers.TimeManagement import TimePoint, TimeAmount
from ..Interfaces.ITaskModel import ITaskModel


class TaskModel(ITaskModel):
    def __init__(self, description: str, context: str, start: int, due: int, severity: float, totalCost: float, investedEffort: float, status: str, calm: str, project: str, index: int):
        self._description: str = description
        self._context: str = context
        self._start: int = int(start)
        self._due: int = int(due)
        self._severity: float = float(severity)
        self._totalCost: float = float(totalCost)
        self._investedEffort: float = float(investedEffort)
        self._status: str = status
        self._calm: bool = True if calm.upper().startswith("TRUE") else False
        self._project: str = project
        self._index: int = index

    def getDescription(self) -> str:
        """
        Gets the task description. This is the task title with the addition of the project where the task is stored.

        Returns:
            str: The enriched task description.
        """
        return f"{self._description}{'' if self._project == '' else f' @ {self._project}'}"

    def getContext(self) -> str:
        return self._context

    def getStart(self) -> TimePoint:
        return TimePoint(datetime.datetime.fromtimestamp(self._start / 1e3))

    def getDue(self) -> TimePoint:
        return TimePoint(datetime.datetime.fromtimestamp(self._due / 1e3)).strip_time()

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

    def getProject(self) -> str:
        """
        Gets the project where the task is stored.

        Returns:
            str: The project name.
        """
        return self._project

    def setDescription(self, description: str) -> None:
        self._description = description

    def setContext(self, context: str) -> None:
        self._context = context

    def setStart(self, start: TimePoint) -> None:
        self._start = start.as_int()
        if self._due < start.strip_time().as_int():
            self._due = start.strip_time().as_int()

    def setDue(self, due: TimePoint) -> None:
        self._due = due.as_int()
        if self._start > due.as_int():
            self._start = due.as_int()

    def setSeverity(self, severity: float) -> None:
        self._severity = severity

    def setTotalCost(self, totalCost: TimeAmount) -> None:
        self._totalCost = totalCost.as_pomodoros()

    def setInvestedEffort(self, investedEffort: TimeAmount) -> None:
        self._investedEffort = investedEffort.as_pomodoros()

    def setStatus(self, status: str) -> None:
        self._status = status

    def setCalm(self, calm: bool) -> None:
        self._calm = calm

    def calculateRemainingTime(self) -> TimeAmount:
        dueDate = self.getDue().as_int()

        currentDate = TimePoint.now().as_int()
        d = (dueDate - currentDate) / (datetime.timedelta(days=1).total_seconds() * 1000)
        d = max(0, d)
        d = ceil(d)
        return TimeAmount(f"{d}d")

    def __eq__(self, other: ITaskModel):  # type: ignore
        return self._index == other._index  # type: ignore
