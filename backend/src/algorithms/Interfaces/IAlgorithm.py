from abc import ABC, abstractmethod
from typing import List

from src.Interfaces.ITaskModel import ITaskModel


class IAlgorithm(ABC):
    """
    Interface for algorithm implementations.
    All algorithms should inherit from this class and implement the apply method.
    """

    @abstractmethod
    def apply(self, taskList: List[ITaskModel]) -> List[ITaskModel]:
        """
        Execute the algorithm with the given parameters.

        Args:
            taskList (List[ITaskModel]): The list of tasks to be processed by the algorithm.

        Returns:
            List[ITaskModel]: The list of tasks after applying the algorithm.
        """
        pass

    @abstractmethod
    def getDescription(self) -> str:
        """
        Get the description of the algorithm.

        Returns:
            str: The description of the algorithm.
        """
        pass
