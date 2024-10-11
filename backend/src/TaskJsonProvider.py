# class interface

from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .Interfaces.IFileBroker import IFileBroker, FileRegistry
import json

class TaskJsonProvider(ITaskJsonProvider):
    
    def __init__(self, fileBroker: IFileBroker):
        self.fileBroker = fileBroker

    def getJson(self) -> dict:
        return self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
    
    def saveJson(self, json: dict):
        self.fileBroker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, json)