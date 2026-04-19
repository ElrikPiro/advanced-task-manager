from abc import ABC, abstractmethod


class ILogger(ABC):

    @abstractmethod
    def info(self, message: str) -> None:
        """
        Logs an informational message.
        """
        pass

    @abstractmethod
    def debug(self, message: str) -> None:
        """
        Logs a debug message.
        """
        pass

    @abstractmethod
    def warning(self, message: str) -> None:
        """
        Logs a warning message.
        """
        pass

    @abstractmethod
    def error(self, message: str) -> None:
        """
        Logs an error message.
        """
        pass

    @abstractmethod
    def critical(self, message: str) -> None:
        """
        Logs a critical message.
        """
        pass
