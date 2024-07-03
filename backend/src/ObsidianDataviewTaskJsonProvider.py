import os
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IJsonLoader import IJsonLoader

class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, jsonLoader : IJsonLoader):
        self.filename = "tareas.json"
        self.JsonLoader = jsonLoader

    def getJson(self) -> str:
        appdata = os.getenv('APPDATA')
        jsonPath = appdata + "/obsidian/" + self.filename
        #calls the load_json method from the JsonLoader class
        return self.JsonLoader.load_json(jsonPath)