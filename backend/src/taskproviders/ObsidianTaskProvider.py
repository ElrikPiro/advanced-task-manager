import datetime
import json
import threading

from ..Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from ..Interfaces.ITaskProvider import ITaskProvider
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..taskmodels.ObsidianTaskModel import ObsidianTaskModel
from ..wrappers.TimeManagement import TimePoint, TimeAmount
from typing import List

class ObsidianTaskProvider(ITaskProvider):
    def __init__(self, taskJsonProvider: ITaskJsonProvider, fileBroker : IFileBroker):
        self.TaskJsonProvider = taskJsonProvider
        self.fileBroker = fileBroker
        self.service = threading.Thread(target=self._serviceThread)
        self.serviceRunning = True
        self.service.start()
        self.lastJson : dict = {}
        self.lastTaskList : List[ITaskModel] = []
        self.onTaskListUpdatedCallbacks : list[callable] = []

    def dispose(self):
        self.serviceRunning = False
        self.service.join()

    def _serviceThread(self):
        while self.serviceRunning:
            newTaskList = self._getTaskList()
            if not self.compare(self.lastTaskList, newTaskList):
                self.lastTaskList = newTaskList
                for callback in self.onTaskListUpdatedCallbacks:
                    callback()
            threading.Event().wait(10)

    def _getTaskList(self) -> List[ITaskModel]:
        obsidianJson : dict = self.TaskJsonProvider.getJson()
        if obsidianJson == self.lastJson:
            return self.lastTaskList
        else:
            self.lastJson = obsidianJson
        taskListJson : dict = obsidianJson["tasks"]
        taskList : List[ITaskModel] = []
        for task in taskListJson:
            try:
                obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], TimePoint.from_string(task["starts"]), TimePoint.from_string(task["due"]), task["severity"], TimeAmount(task["total_cost"]), TimeAmount(task["effort_invested"]), task["status"], task["file"], task["line"], task["calm"])
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
        start = task.getStart().datetime_representation.strftime("%Y-%m-%dT%H:%M")
        due = task.getDue().datetime_representation.strftime("%Y-%m-%d")
        severity = task.getSeverity()
        totalCost = task.getTotalCost()
        investedEffort = task.getInvestedEffort()
        status = task.getStatus()
        calm = "true" if task.getCalm() else "false"

        taskLine = f"- [{status}] {description} [track:: {context}], [starts:: {start}], [due:: {due}], [severity:: {severity}], [remaining_cost:: {totalCost+investedEffort}], [invested:: {investedEffort}], [calm:: {calm}]\n"
        
        file = ""
        lineNumber = -1
        if not isinstance(task, ObsidianTaskModel) or task.getFile() == "" or task.getLine() == -1:
            lines = self.fileBroker.readFileContent(FileRegistry.OBSIDIAN_TASKS_MD).split("\n")
            newLines = []

            numLines = 1
            for line in lines:
                if line.find("- [x]") == -1:
                    newLines.append(line)
                    numLines += 1
            newLines.append(taskLine)
            
            #TODO: this constant must be changed to be get from a config value
            task.setFile("ObsidianTaskProvider.md")
            task.setLine(numLines - 1)
            self.fileBroker.writeFileContent(FileRegistry.OBSIDIAN_TASKS_MD, "\n".join(newLines))
        else:
            ObsidianTask : ObsidianTaskModel = task
            file = ObsidianTask.getFile()
            lineNumber = ObsidianTask.getLine()
            fileLines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)
            lineOfInterest = fileLines[lineNumber]
            fileLines[lineNumber] = lineOfInterest.split("- [")[0] + taskLine
            self.fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, file, fileLines)

    def createDefaultTask(self, description: str):
        starts = TimePoint.now()
        due = TimePoint.today()
        
        severity = 1.0
        invested = TimeAmount("0")
        status = " "
        calm = "False"

        task = ObsidianTaskModel(description, "workstation", starts, due, 1, severity, invested, status, "", -1, calm)
        self.saveTask(task)
        return task
    
    def getTaskMetadata(self, task: ITaskModel) -> str:
        file = task.getFile()
        line = task.getLine()
        fileLines = fileLines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)

        metadata = []
        for i in range(max(line, 0), min(line+5,len(fileLines))):
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
    
    def _exportJson(self) -> bytearray:
        jsonData = self.TaskJsonProvider.getJson()
        jsonStr = json.dumps(jsonData, indent=4)
        return bytearray(jsonStr, "utf-8")

    def exportTasks(self, selectedFormat : str) -> bytearray:
        supportedFormats : dict = {
            "json": self._exportJson,
        }

        return supportedFormats[selectedFormat]()
    
    def importTasks(self, selectedFormat : str):
        raise NotImplementedError("Importing tasks is not supported for ObsidianTaskProvider")
