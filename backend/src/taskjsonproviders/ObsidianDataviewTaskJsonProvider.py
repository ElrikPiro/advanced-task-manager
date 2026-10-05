from src.Utils import TaskJsonType
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..Interfaces.IFileBroker import IFileBroker, FileRegistry


class ObsidianDataviewTaskJsonProvider(ITaskJsonProvider):

    def __init__(self, fileBroker: IFileBroker) -> None:
        self.fileBroker = fileBroker

    def getJson(self) -> TaskJsonType:
        retval = self.fileBroker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON)
        if not isinstance(retval, dict):
            raise TypeError("Obsidian task JSON must contain an object at the top level")
        return retval

    def discover(self) -> TaskJsonType:
        # Dataview already materializes its current task view in the source
        # JSON; it has no additional reconciliation to perform.
        return self.getJson()
        
    def saveJson(self, json: TaskJsonType) -> None:
        # do nothing
        pass
