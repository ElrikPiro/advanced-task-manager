import os
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader

class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, jsonLoader : IJsonLoader):
        self.filename = "tareas.json"
        self.JsonLoader = jsonLoader

    def getJson(self) -> dict:
        appdata = os.getenv('APPDATA')
        jsonPath = appdata + "/obsidian/" + self.filename
        return self.JsonLoader.load_json(jsonPath)
    
    def saveJson(self, json: dict):
        pass