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
    def getInvestedEffort(self) -> float: #TODO: change to TimeAmount
        pass

    @abstractmethod
    def getStatus(self) -> str:
        pass

    @abstractmethod
    def getCalm(self) -> bool:
        pass

    @abstractmethod
    def setDescription(self, description: str):
        pass

    @abstractmethod
    def setContext(self, context: str):
        pass

    @abstractmethod
    def setStart(self, start: int): #TODO: change to TimePoint
        pass

    @abstractmethod
    def setDue(self, due: int): #TODO: change to TimePoint
        pass

    @abstractmethod
    def setSeverity(self, severity: float):
        pass

    @abstractmethod
    def setTotalCost(self, totalCost: TimeAmount):
        pass

    @abstractmethod
    def setInvestedEffort(self, investedEffort: float): #TODO: change to TimeAmount
        pass

    @abstractmethod
    def setStatus(self, status: str):
        pass

    @abstractmethod
    def setCalm(self, calm: bool):
        pass

    @abstractmethod
    def calculateRemainingTime(self) -> int: #TODO: change to TimeAmount
        pass

    @abstractmethod
    def __eq__(self, other):
        pass

