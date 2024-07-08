from abc import ABC, abstractmethod

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
    def getStart(self) -> int:
        pass

    @abstractmethod
    def getDue(self) -> int:
        pass

    @abstractmethod
    def getSeverity(self) -> float:
        pass

    @abstractmethod
    def getTotalCost(self) -> float:
        pass

    @abstractmethod
    def getInvestedEffort(self) -> float:
        pass

    @abstractmethod
    def getStatus(self) -> str:
        pass

    @abstractmethod
    def setDescription(self, description: str):
        pass

    @abstractmethod
    def setContext(self, context: str):
        pass

    @abstractmethod
    def setStart(self, start: int):
        pass

    @abstractmethod
    def setDue(self, due: int):
        pass

    @abstractmethod
    def setSeverity(self, severity: float):
        pass

    @abstractmethod
    def setTotalCost(self, totalCost: float):
        pass

    @abstractmethod
    def setInvestedEffort(self, investedEffort: float):
        pass

    @abstractmethod
    def setStatus(self, status: str):
        pass

    @abstractmethod
    def calculateRemainingTime(self) -> int:
        pass

    