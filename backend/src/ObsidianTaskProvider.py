import datetime
import os
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
    
    def saveTask(self, task: ITaskModel):
        description = task.getDescription().split("@")[0].strip()
        context = task.getContext()
        start = datetime.datetime.fromtimestamp(task.getStart() / 1e3).strftime("%Y-%m-%dT%H:%M")
        due = datetime.datetime.fromtimestamp(task.getDue() / 1e3).strftime("%Y-%m-%d")
        severity = task.getSeverity()
        totalCost = task.getTotalCost()
        investedEffort = task.getInvestedEffort()
        status = task.getStatus()
        calm = "true" if task.getCalm() else "false"

        taskLine = f"- [{status}] {description} [track:: {context}], [starts:: {start}], [due:: {due}], [severity:: {severity}], [remaining_cost:: {totalCost}], [invested:: {investedEffort}], [calm:: {calm}]\n"
        
        file = None
        lineNumber = None
        if not isinstance(task, ObsidianTaskModel):
            file = "ObsidianTaskProvider.md"
            # if file doesnt exist in vault path, create it
            if not os.path.exists(self.vaultPath + "/" + file):
                with open(self.vaultPath + file, "w") as file:
                    file.write("# Task list\n\n")
                    file.write(taskLine)
        else:
            ObsidianTask : ObsidianTaskModel = task
            file = ObsidianTask.getFile()
            lineNumber = ObsidianTask.getLine()
            fileLines = []
            with open(self.vaultPath + "/" + file, "r") as f:
                fileLines = f.readlines()
            lineOfInterest = fileLines[lineNumber]
            fileLines[lineNumber] = lineOfInterest.split("- [")[0] + taskLine
            with open(self.vaultPath + "/" + file, "w") as f:
                f.writelines(fileLines)
