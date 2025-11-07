from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider, TaskJsonType
from ..Interfaces.IFileBroker import FileContent, IFileBroker, FileRegistry


class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker) -> None:
        self.fileBroker = fileBroker

    def getJson(self) -> TaskJsonType:
        retval: FileContent = self.fileBroker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON)
        if isinstance(retval, dict):
            return retval
        
        return {"": []}
        
    def saveJson(self, json: TaskJsonType) -> None:
        # do nothing
        pass
