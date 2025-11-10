from abc import ABC, abstractmethod
from ..wrappers.TimeManagement import TimePoint, TimeAmount


# Interface for TaskModel
# Datatype contains the following fields:
# - description: str
# - context: str
# - start: datetime (int)
# - due: datetime (int)
# - severity: float
# - totalCost: float
# - investedEffort: float
# - status: str
class ITaskModel(ABC):

    @abstractmethod
    def getDescription(self) -> str:
        pass

    @abstractmethod
    def getContext(self) -> str:
        pass

    @abstractmethod
    def getStart(self) -> TimePoint:
        pass

    @abstractmethod
    def getDue(self) -> TimePoint:
        pass

    @abstractmethod
    def getSeverity(self) -> float:
        pass

    @abstractmethod
    def getTotalCost(self) -> TimeAmount:
        pass

    @abstractmethod
    def getInvestedEffort(self) -> TimeAmount:
        pass

    @abstractmethod
    def getStatus(self) -> str:
        pass

    @abstractmethod
    def getCalm(self) -> bool:
        pass

    @abstractmethod
    def getProject(self) -> str:
        pass

    @abstractmethod
    def setDescription(self, description: str) -> None:
        pass

    @abstractmethod
    def setContext(self, context: str) -> None:
        pass

    @abstractmethod
    def setStart(self, start: TimePoint) -> None:
        pass

    @abstractmethod
    def setDue(self, due: TimePoint) -> None:
        pass

    @abstractmethod
    def setSeverity(self, severity: float) -> None:
        pass

    @abstractmethod
    def setTotalCost(self, totalCost: TimeAmount) -> None:
        pass

    @abstractmethod
    def setInvestedEffort(self, investedEffort: TimeAmount) -> None:
        pass

    @abstractmethod
    def setStatus(self, status: str) -> None:
        pass

    @abstractmethod
    def setCalm(self, calm: bool) -> None:
        pass

    @abstractmethod
    def calculateRemainingTime(self) -> TimeAmount:
        pass

    @abstractmethod
    def __eq__(self, other):  # type: ignore
        pass
