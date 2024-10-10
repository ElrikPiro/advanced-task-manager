import os
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader
from .Interfaces.IFileBroker import IFileBroker, FileRegistry

class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, json_loader : IJsonLoader, fileBroker: IFileBroker):
        self.JsonLoader = json_loader
        self.fileBroker = fileBroker

    def getJson(self) -> dict:
        jsonData = self.fileBroker.readFileContent(FileRegistry.OBSIDIAN_TASKS_JSON)
        return self.JsonLoader.load_json(jsonData)
    
    def saveJson(self, json: dict):
        #do nothing
        pass