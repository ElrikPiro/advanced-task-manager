from abc import ABC, abstractmethod

class IReportingService(ABC):

    @abstractmethod
    def listenForEvents(self):
        pass

    @abstractmethod
    def dispose(self):
        pass