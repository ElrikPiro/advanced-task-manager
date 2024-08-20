# class interface

from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader
from json import dump

class TaskJsonProvider(ITaskJsonProvider):
    
    def __init__(self, path, json_loader):
        self.path : str = path
        self.jsonLoader : IJsonLoader = json_loader

    def getJson(self) -> dict:
        return self.jsonLoader.load_json(self.path)
    
    def saveJson(self, json: dict):
        with open(self.path, "w") as file:
            dump(json, file, indent=4)