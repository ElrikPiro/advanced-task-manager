# class interface

from abc import ABC, abstractmethod

VALID_PROJECT_STATUS = [
    "open",
    "closed",
    "on-hold",
]

TaskJsonElementType = dict[str, str]
TaskJsonListType = list[TaskJsonElementType]
ProjectJsonElementType = dict[str, str]
ProjectJsonListType = list[ProjectJsonElementType]
TaskJsonType = dict[str, TaskJsonListType | ProjectJsonListType]


class ITaskJsonProvider(ABC):

    @abstractmethod
    def getJson(self) -> TaskJsonType:
        """
        Gets the tasks json.

        Returns:
            dict: The tasks json.
        """
        pass

    @abstractmethod
    def saveJson(self, json: TaskJsonType) -> None:
        pass
