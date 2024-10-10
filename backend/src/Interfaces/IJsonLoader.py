from abc import ABC, abstractmethod

class IJsonLoader(ABC):

    @abstractmethod
    def load_json(self, jsonStr: str) -> dict:
        pass