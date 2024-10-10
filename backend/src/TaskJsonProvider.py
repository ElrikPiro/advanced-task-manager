# class interface

from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader
from .Interfaces.IFileBroker import IFileBroker, FileRegistry
import json

class TaskJsonProvider(ITaskJsonProvider):
    
    def __init__(self, json_loader : IJsonLoader, fileBroker: IFileBroker):
        self.jsonLoader = json_loader
        self.fileBroker = fileBroker

    def getJson(self) -> dict:
        jsonFile = self.fileBroker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON)
        return self.jsonLoader.load_json(jsonFile)
    
    def saveJson(self, json: dict):
        #TODO: use the fileBroker to save the json
        # with open(self.path, "w") as file:
        #     dump(json, file, indent=4)
        pass