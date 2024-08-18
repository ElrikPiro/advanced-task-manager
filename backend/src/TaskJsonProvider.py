# class interface

from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader
from json import dump

class TaskJsonProvider(ITaskJsonProvider):
    
    def __init__(self, path, jsonLoader):
        self.path : str = path
        self.jsonLoader : IJsonLoader = jsonLoader

    def getJson(self) -> dict:
        return self.jsonLoader.load_json(self.path)
    
    def saveJson(self, json: dict):
        dump(json, self.path, indent=4)
        pass