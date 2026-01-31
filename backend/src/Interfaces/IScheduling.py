from abc import ABC, abstractmethod
from typing import List
from .ITaskModel import ITaskModel


class IScheduling(ABC):

    @abstractmethod
    def schedule(self, task: ITaskModel, param: str) -> List[ITaskModel]:
        pass
