from typing import TextIO
from datetime import datetime

from src.Interfaces.ILogger import ILogger


class StreamLogger(ILogger):
    """
    A logger implementation that writes formatted log messages
    to a text output stream (e.g., sys.stdout, sys.stderr).
    """

    LOG_FORMAT = "[{timestamp}] [{level}] {message}"

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def _log(self, level: str, message: str) -> None:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        formatted = self.LOG_FORMAT.format(
            timestamp=timestamp,
            level=level,
            message=message,
        )
        self._stream.write(formatted + "\n")
        self._stream.flush()

    def info(self, message: str) -> None:
        self._log("INFO", message)

    def debug(self, message: str) -> None:
        self._log("DEBUG", message)

    def warning(self, message: str) -> None:
        self._log("WARNING", message)

    def error(self, message: str) -> None:
        self._log("ERROR", message)

    def critical(self, message: str) -> None:
        self._log("CRITICAL", message)
