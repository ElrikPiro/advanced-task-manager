from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .ObsidianTaskModel import ObsidianTaskModel
from typing import List

class ObsidianTaskProvider(ITaskProvider):
    def __init__(self, taskJsonProvider: ITaskJsonProvider, vaultPath: str):
        self.TaskJsonProvider = taskJsonProvider
        self.vaultPath = vaultPath
        pass

    def getTaskList(self) -> List[ITaskModel]:
        obsidianJson : dict = self.TaskJsonProvider.getJson()
        taskListJson : dict = obsidianJson["tasks"]
        taskList : List[ITaskModel] = []
        for task in taskListJson:
            try:
                obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], task["starts"], task["due"], task["severity"], task["total_cost"], task["effort_invested"], task["status"], task["file"], task["line"], task["calm"], vaultPath=self.vaultPath)
                taskList.append(obsidianTask)
            except Exception as e:
                # print error cause and skip task
                print(f"Error creating task from json: "+ task["taskText"] + f" : {repr(e)}")
                print(f"skipping...")
                continue
        return taskList
    
    def getTaskListAttribute(self, string: str) -> str:
        return self.TaskJsonProvider.getJson()[string]