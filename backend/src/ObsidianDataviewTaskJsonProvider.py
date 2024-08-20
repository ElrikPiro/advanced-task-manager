import os
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader

class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, json_loader : IJsonLoader):
        self.filename = "tareas.json"
        self.JsonLoader = json_loader

    def getJson(self) -> dict:
        appdata = os.getenv('APPDATA')
        json_path = appdata + "/obsidian/" + self.filename
        return self.JsonLoader.load_json(json_path)
    
    def saveJson(self, json: dict):
        #do nothing
        pass