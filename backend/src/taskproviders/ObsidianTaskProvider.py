import datetime
import json
import threading

from ..Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from ..Interfaces.ITaskProvider import ITaskProvider
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..taskmodels.ObsidianTaskModel import ObsidianTaskModel
from typing import List


class ObsidianTaskProvider(ITaskProvider):
    def __init__(self, taskJsonProvider: ITaskJsonProvider, fileBroker: IFileBroker, disableThreading: bool = False):
        self.TaskJsonProvider = taskJsonProvider
        self.fileBroker = fileBroker
        self.serviceRunning = True
        self.lastJson: dict = {}
        self.lastTaskList: List[ITaskModel] = []
        self.onTaskListUpdatedCallbacks: list[callable] = []
        self.__disableThreading = disableThreading
        if not self.__disableThreading:
            self.service = threading.Thread(target=self.__serviceThread)
            self.service.start()

    def dispose(self):
        if not self.__disableThreading:
            self.serviceRunning = False
            self.service.join()

    def __serviceThread(self):
        while self.serviceRunning:
            newTaskList = self.__getTaskList()
            if not self.compare(self.lastTaskList, newTaskList):
                self.lastTaskList = newTaskList
                for callback in self.onTaskListUpdatedCallbacks:
                    callback()
            threading.Event().wait(10)

    def __getTaskList(self) -> List[ITaskModel]:
        obsidianJson: dict = self.TaskJsonProvider.getJson()
        if obsidianJson == self.lastJson:
            return self.lastTaskList
        else:
            self.lastJson = obsidianJson
        taskListJson: dict = obsidianJson["tasks"]
        taskList: List[ITaskModel] = []
        for task in taskListJson:
            try:
                obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], task["starts"], task["due"], task["severity"], task["total_cost"], task["effort_invested"], task["status"], task["file"], task["line"], task["calm"])
                taskList.append(obsidianTask)
            except Exception as e:
                print(f"Error while reading task: {e}")
                continue
        return taskList

    def getTaskList(self) -> List[ITaskModel]:
        return self.lastTaskList

    def getTaskListAttribute(self, string: str) -> str:
        try:
            return self.lastJson[string]
        except Exception:
            return self.TaskJsonProvider.getJson()[string]

    def _getTaskLine(self, task: ITaskModel) -> str:
        context = task.getContext()
        description = task.getDescription().split("@")[0].replace(f"({context})", "").strip()
        start = str(task.getStart())
        due = str(task.getDue())
        severity = task.getSeverity()
        totalCost = task.getTotalCost().as_pomodoros()
        investedEffort = task.getInvestedEffort().as_pomodoros()
        status = task.getStatus()
        calm = "true" if task.getCalm() else "false"

        return f"- [{status}] {description} [track:: {context}], [starts:: {start}], [due:: {due}], [severity:: {severity}], [remaining_cost:: {totalCost+investedEffort}], [invested:: {investedEffort}], [calm:: {calm}]\n"

    def saveTask(self, task: ITaskModel):
        taskLine = self._getTaskLine(task)

        file = ""
        lineNumber = -1
        if not isinstance(task, ObsidianTaskModel) or task.getFile() == "" or task.getLine() == -1:
            lines = self.fileBroker.readFileContent(FileRegistry.OBSIDIAN_TASKS_MD).split("\n")
            newLines = []

            numLines = 1
            for line in lines:
                if line.find("- [x]") == -1 and len(line) > 0:
                    newLines.append(line)
                    numLines += 1
            newLines.append(taskLine)

            # TODO: this constant must be changed to be get from a config value
            if isinstance(task, ObsidianTaskModel):
                task.setFile("ObsidianTaskProvider.md")
                task.setLine(numLines - 1)

            self.fileBroker.writeFileContent(FileRegistry.OBSIDIAN_TASKS_MD, "\n".join(newLines))
        else:
            ObsidianTask: ObsidianTaskModel = task
            file = ObsidianTask.getFile()
            lineNumber = ObsidianTask.getLine()
            fileLines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)
            if lineNumber >= len(fileLines):
                lineNumber = len(fileLines)
                fileLines.append(taskLine)
            else:
                lineOfInterest = fileLines[lineNumber]
                fileLines[lineNumber] = lineOfInterest.split("- [")[0] + taskLine
            self.fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, file, fileLines)

    def createDefaultTask(self, description: str):
        starts = int(datetime.datetime.now().timestamp() * 1e3)
        due = int(datetime.datetime.today().timestamp() * 1e3)
        starts = starts - starts % 60000
        due = due - due % 60000

        severity = 1.0
        invested = 0.0
        status = " "
        calm = "False"

        task = ObsidianTaskModel(description, "workstation", starts, due, 1, severity, invested, status, "", -1, calm)
        return task

    def getTaskMetadata(self, task: ITaskModel) -> str:
        file = task.getFile()
        line = task.getLine()
        fileLines = fileLines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)

        metadata = []
        for i in range(max(line, 0), min(line + 5, len(fileLines))):
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
        taskList = self.__getTaskList()
        jsonStr = self.__generateExportJson(taskList)
        return bytearray(jsonStr, "utf-8")

    def exportTasks(self, selectedFormat: str) -> bytearray:
        supportedFormats: dict = {
            "json": self._exportJson,
        }

        return supportedFormats[selectedFormat]()

    def importTasks(self, selectedFormat: str):
        raise NotImplementedError("Importing tasks is not supported for ObsidianTaskProvider")

    def __generateExportJson(self, taskList: List[ITaskModel]) -> str:
        tasks = []
        for task in taskList:
            taskDict = {
                "description": task.getDescription(),
                "context": task.getContext(),
                "start": task.getStart().as_int(),
                "due": task.getDue().as_int(),
                "severity": task.getSeverity(),
                "totalCost": task.getTotalCost().as_pomodoros(),
                "investedEffort": task.getInvestedEffort().as_pomodoros(),
                "status": task.getStatus(),
                "calm": task.getCalm()
            }
            tasks.append(taskDict)
        return json.dumps({
            "tasks": tasks
        }, indent=4)
