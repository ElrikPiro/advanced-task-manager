from abc import ABC, abstractmethod
import datetime

from .ITaskModel import ITaskModel

class IStatisticsService(ABC):

    @abstractmethod
    def doWork(self, date : datetime.date, work_units : float):
        pass

    @abstractmethod
    def getWorkDone(self, date : datetime.date) -> float:
        pass

    @abstractmethod
    def getWorkloadStats(self, taskList : list[ITaskModel]) -> list:
        pass

    @abstractmethod
    def initialize(self):
        pass