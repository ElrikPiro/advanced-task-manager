from abc import ABC, abstractmethod

class IJsonLoader(ABC):

    @abstractmethod
    def load_json(self, file_path: str, data: dict) -> dict:
        pass