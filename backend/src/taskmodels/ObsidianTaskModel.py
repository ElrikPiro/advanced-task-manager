from ..Interfaces.ITaskModel import ITaskModel
from .TaskModel import TaskModel


class ObsidianTaskModel(TaskModel):
    def __init__(self, description: str, context: str, start: int, due: int, severity: float, totalCost: float, investedEffort: float, status: str, file: str, line: int, calm: str, raised: str | None, waited: str | None):
        self._description: str = description
        self._context: str = context
        self._start: int = int(start)
        self._due: int = int(due)
        self._severity: float = float(severity)
        self._totalCost: float = float(totalCost)
        self._investedEffort: float = float(investedEffort)
        self._status: str = status
        self._file: str = "/".join(file.split("\\"))
        self._line: int = int(line)
        self._calm: bool = True if calm.upper().startswith("TRUE") else False
        self._raised = raised
        self._waited = waited

    # Overrided
    def getDescription(self) -> str:
        """
        Gets the task description. This is the task title with the addition of the file and line where the task is stored.

        Returns:
            str: The enriched task description.
        """
        return f"({self._context}) {self._description} @ '{self.getProject()}'"

    def getProject(self) -> str:
        """
        Gets the file name with the line number where the task is stored.
        """
        slash = "/"
        dot = "."
        return f"{self._file.split(slash).pop().split(dot)[0]}:{self._line}"

    def __eq__(self, other: ITaskModel):  # type: ignore
        return self.getEventRaised() == other.getEventRaised() and self.getEventWaited() == other.getEventWaited() and self.getDescription() == other.getDescription() and self.getContext() == other.getContext() and self.getStart() == other.getStart() and self.getDue() == other.getDue() and self.getSeverity() == other.getSeverity() and self.getTotalCost().as_pomodoros() == other.getTotalCost().as_pomodoros() and self.getInvestedEffort().as_pomodoros() == other.getInvestedEffort().as_pomodoros() and self.getStatus() == other.getStatus() and self.getFile() == other.getFile() and self.getLine() == other.getLine() and self.getCalm() == other.getCalm()  # type: ignore

    # Class methods
    def getFile(self) -> str:
        return self._file

    def getLine(self) -> int:
        return self._line

    def setFile(self, file: str) -> None:
        self._file = "/".join(file.split("\\"))

    def setLine(self, line: int) -> None:
        self._line = line
