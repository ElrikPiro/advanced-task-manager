from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .ObsidianTaskModel import ObsidianTaskModel
from typing import List

class ObsidianTaskProvider(ITaskProvider):
    def __init__(self, taskJsonProvider: ITaskJsonProvider):
        self.TaskJsonProvider = taskJsonProvider
        pass

    def getTaskList(self) -> List[ITaskModel]:
        obsidianJson : dict = self.TaskJsonProvider.getJson()
        taskListJson : dict = obsidianJson# obsidianJson["tasks"]
        taskList : List[ITaskModel] = []
        for task in taskListJson:
            try:
                obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], task["starts"], task["due"], task["severity"], task["total_cost"], task["effort_invested"], task["status"], task["file"], task["line"], task["calm"])
                taskList.append(obsidianTask)
            except Exception as e:
                # print error cause and skip task
                print(f"Error creating task from json: "+ task["taskText"] + f" : {repr(e)}")
                print(f"skipping...")
                continue
        return taskList