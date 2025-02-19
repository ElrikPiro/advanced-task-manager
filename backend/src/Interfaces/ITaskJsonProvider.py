# class interface

from abc import ABC, abstractmethod


class ITaskJsonProvider(ABC):

    @abstractmethod
    def getJson(self) -> dict:
        pass

    @abstractmethod
    def saveJson(self, json: dict):
        pass
