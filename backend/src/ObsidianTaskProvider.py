import datetime
import os
import threading
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskJsonProvider import ITaskJsonProvider
from .ObsidianTaskModel import ObsidianTaskModel
from typing import List

class ObsidianTaskProvider(ITaskProvider):
    def __init__(self, taskJsonProvider: ITaskJsonProvider, vaultPath: str):
        self.TaskJsonProvider = taskJsonProvider
        self.vaultPath = vaultPath
        self.service = threading.Thread(target=self._serviceThread)
        self.service.start()
        self.serviceRunning = True
        self.lastTaskList : List[ITaskModel] = []
        self.onTaskListUpdatedCallbacks : list[callable] = []
        pass

    def __del__(self):
        self.serviceRunning = False
        self.service.join()
        pass

    def _serviceThread(self):
        while self.serviceRunning:
            newTaskList = self._getTaskList()
            if not self.compare(self.lastTaskList, newTaskList):
                self.lastTaskList = newTaskList
                for callback in self.onTaskListUpdatedCallbacks:
                    callback()
            threading.Event().wait(10)
        pass

    def _getTaskList(self) -> List[ITaskModel]:
        obsidianJson : dict = self.TaskJsonProvider.getJson()
        taskListJson : dict = obsidianJson["tasks"]
        taskList : List[ITaskModel] = []
        for task in taskListJson:
            try:
                obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], task["starts"], task["due"], task["severity"], task["total_cost"], task["effort_invested"], task["status"], task["file"], task["line"], task["calm"], vaultPath=self.vaultPath)
                taskList.append(obsidianTask)
            except Exception as e:
                # print error cause and skip task
                # print(f"Error creating task from json: "+ task["taskText"] + f" : {repr(e)}")
                # print(f"skipping...")
                continue
        return taskList

    def getTaskList(self) -> List[ITaskModel]:
        return self.lastTaskList
    
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

        taskLine = f"- [{status}] {description} [track:: {context}], [starts:: {start}], [due:: {due}], [severity:: {severity}], [remaining_cost:: {totalCost+investedEffort}], [invested:: {investedEffort}], [calm:: {calm}]\n"
        
        file = ""
        lineNumber = -1
        if not isinstance(task, ObsidianTaskModel) or task.getFile() == "" or task.getLine() == -1:
            file = "ObsidianTaskProvider.md"
            # if file doesnt exist in vault path, create it
            if not os.path.exists(self.vaultPath + "\\" + file):
                with open(self.vaultPath + file, "w+", encoding='utf-8') as f:
                    f.write("# Task list\n\n")
                    f.write(taskLine)
            else:
                # clean completed tasks
                lines = []
                with open(self.vaultPath + "\\" + file, "r", encoding='utf-8') as f:
                    lines = f.readlines()

                numLines = 1
                with open(self.vaultPath + "\\" + file, "w", encoding='utf-8') as f:
                    for line in lines:
                        if line.find("- [x]") == -1:
                            f.write(line)
                            numLines += 1
                    f.write(taskLine)
                task.setFile(file)
                task.setLine(numLines - 1)
        else:
            ObsidianTask : ObsidianTaskModel = task
            file = ObsidianTask.getFile()
            lineNumber = ObsidianTask.getLine()
            fileLines = []
            with open(self.vaultPath + "/" + file, "r", encoding='utf-8') as f:
                fileLines = f.readlines()
            lineOfInterest = fileLines[lineNumber]
            fileLines[lineNumber] = lineOfInterest.split("- [")[0] + taskLine
            with open(self.vaultPath + "/" + file, "w", encoding='utf-8') as f:
                f.writelines(fileLines)

    def createDefaultTask(self, description: str):
        starts = int(datetime.datetime.now().timestamp() * 1e3)
        due = int(datetime.datetime.today().timestamp() * 1e3)
        severity = 1.0
        invested = 0.0
        status = " "
        calm = "false"

        task = ObsidianTaskModel(description, "workstation", starts, due, 1, severity, invested, status, "", -1, calm, vaultPath=self.vaultPath)
        self.saveTask(task)
        return task
    
    def getTaskMetadata(self, task: ITaskModel) -> str:
        file = task.getFile()
        line = task.getLine()
        fileLines = []
        with open(self.vaultPath + "/" + file, "r", encoding='utf-8') as f:
            fileLines = f.readlines()

        metadata = []
        for i in range(max(line-1, 0), min(line+5,len(fileLines)-1)):
            metadata.append(fileLines[i])
        
        return "".join(metadata)
    
    def registerTaskListUpdatedCallback(self, callback):
        self.onTaskListUpdatedCallbacks.append(callback)

    def compare(self, list1, list2):
        if len(list1) != len(list2):
            return False
        for i in range(len(list1)):
            if list1[i] != list2[i]:
                return False
        return True
