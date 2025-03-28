from abc import ABC, abstractmethod
import datetime

from .ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimePoint, TimeAmount


class IStatisticsService(ABC):

    @abstractmethod
    def doWork(self, date: datetime.date, work_units: TimeAmount, task: ITaskModel):
        """
        Records work done on a task on a given date.

        Params:
            date: The date on which the work was done.
            work_units: The amount of work done.
            task: The task on which the work was done.
        """
        pass

    @abstractmethod
    def getWorkDone(self, date: TimePoint) -> TimeAmount:
        pass

    @abstractmethod
    def getWorkloadStats(self, taskList: list[ITaskModel]) -> list:
        pass

    @abstractmethod
    def initialize(self):
        pass

    @abstractmethod
    def getWorkDoneLog(self) -> list:
        """
        Returns a list of dictionaries representing the work done log.

        Returns:
            A list of dictionaries representing the work done log.
            Fields are the following:
                - timestamp: The timestamp of the work done.
                - work_units: The amount of work done.
                - task: The task on which the work was done.
        """
        pass
