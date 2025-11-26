from abc import ABC, abstractmethod
import datetime

from src.Utils import EventsContent, WorkLogEntry, WorkloadStats

from .ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimePoint, TimeAmount


class IStatisticsService(ABC):

    @abstractmethod
    def doWork(self, date: datetime.date, work_units: TimeAmount, task: ITaskModel) -> None:
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
    def getWorkloadStats(self, taskList: list[ITaskModel]) -> WorkloadStats:
        pass

    @abstractmethod
    def initialize(self) -> None:
        pass

    @abstractmethod
    def getWorkDoneLog(self) -> list[WorkLogEntry]:
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

    @abstractmethod
    def getEventStatistics(self, taskList: list[ITaskModel]) -> EventsContent:
        """
        Analyze event statistics from all tasks to identify raised/waited events and orphans.
        
        Args:
            taskList: List of tasks to analyze for event statistics
            
        Returns:
            EventsContent: Structured data containing event statistics
        """
        pass
