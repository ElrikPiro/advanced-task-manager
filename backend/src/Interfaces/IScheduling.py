from abc import ABC, abstractmethod
from .ITaskModel import ITaskModel

class IScheduling(ABC):

    @abstractmethod
    def schedule(self, task: ITaskModel, param: str) -> None:
        pass