from abc import ABC, abstractmethod


class IReportingService(ABC):

    @abstractmethod
    def listenForEvents(self) -> None:
        pass

    @abstractmethod
    def dispose(self) -> None:
        pass
