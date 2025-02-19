from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry


class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker):
        self.fileBroker = fileBroker

    def getJson(self) -> dict:
        return self.fileBroker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON)

    def saveJson(self, json: dict):
        # do nothing
        pass
