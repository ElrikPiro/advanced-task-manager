import datetime
import json
import threading

from src.Utils import TaskJsonType

from ..Interfaces.IFileBroker import IFileBroker, FileRegistry, VaultRegistry
from ..Interfaces.ITaskProvider import ITaskProvider
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider
from ..taskmodels.ObsidianTaskModel import ObsidianTaskModel
from typing import Callable, List


class ObsidianTaskProvider(ITaskProvider):
    def __init__(self, taskJsonProvider: ITaskJsonProvider, fileBroker: IFileBroker, disableThreading: bool = False):
        self.TaskJsonProvider = taskJsonProvider
        self.fileBroker = fileBroker
        self.serviceRunning = True
        self.lastJson: TaskJsonType = {}
        self.lastTaskList: List[ITaskModel] = []
        self.onTaskListUpdatedCallbacks: list[Callable[[], None]] = []
        self.__disableThreading = disableThreading
        if not self.__disableThreading:
            self.service = threading.Thread(target=self.__serviceThread)
            self.service.start()

    def dispose(self) -> None:
        if not self.__disableThreading:
            self.serviceRunning = False
            self.service.join()

    def __serviceThread(self) -> None:
        while self.serviceRunning:
            newTaskList = self.__getTaskList()
            if not self.compare(self.lastTaskList, newTaskList):
                self.lastTaskList = newTaskList
                for callback in self.onTaskListUpdatedCallbacks:
                    callback()
            threading.Event().wait(10)

    def __getTaskList(self) -> List[ITaskModel]:
        obsidianJson = self.TaskJsonProvider.getJson()
        if obsidianJson == self.lastJson:
            return self.lastTaskList
        else:
            self.lastJson = obsidianJson
        taskListJson = obsidianJson["tasks"]
        taskList: List[ITaskModel] = []
        for task in taskListJson:
            try:
                obsidianTask = ObsidianTaskModel(task["taskText"], task["track"], int(task["starts"]), int(task["due"]), float(task["severity"]), float(task["total_cost"]), float(task["effort_invested"]), task["status"], task["file"], int(task["line"]), task["calm"], task.get("raised"), task.get("waited"))
                taskList.append(obsidianTask)
            except Exception as e:
                print(f"Error while reading task: {e}")
                continue
        return taskList

    def getTaskList(self) -> List[ITaskModel]:
        return self.lastTaskList

    def getTaskListAttribute(self, string: str) -> list[dict[str, str]]:
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
        
        raises = task.getEventRaised()
        raises_str = f", [raises:: {raises}]" if isinstance(raises, str) else ""

        waits = task.getEventWaited()
        waits_str = f", [waits:: {waits}]" if isinstance(waits, str) else ""

        return f"- [{status}] {description} [track:: {context}], [starts:: {start}], [due:: {due}], [severity:: {severity}], [remaining_cost:: {totalCost+investedEffort}], [invested:: {investedEffort}], [calm:: {calm}]{raises_str}{waits_str}\n"

    def saveTask(self, task: ITaskModel) -> None:
        taskLine = self._getTaskLine(task)

        file = ""
        lineNumber = -1
        if not isinstance(task, ObsidianTaskModel) or task.getFile() == "" or task.getLine() == -1:
            lines = self.fileBroker.readFileContent(FileRegistry.OBSIDIAN_TASKS_MD).split("\n")
            newLines: list[str] = []

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

    def createDefaultTask(self, description: str) -> ObsidianTaskModel:
        starts = int(datetime.datetime.now().timestamp() * 1e3)
        due = int(datetime.datetime.today().timestamp() * 1e3)
        starts = starts - starts % 60000
        due = due - due % 60000

        severity = 1.0
        invested = 0.0
        status = " "
        calm = "False"

        task = ObsidianTaskModel(description, "inbox", starts, due, 1, severity, invested, status, "", -1, calm, None, None)
        return task

    def getTaskMetadata(self, task: ITaskModel) -> str:
        if not isinstance(task, ObsidianTaskModel):
            return ""
        
        file = task.getFile()
        line = task.getLine()
        fileLines = fileLines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file)

        metadata: list[str] = []
        for i in range(max(line, 0), min(line + 5, len(fileLines))):
            metadata.append(fileLines[i])

        return "".join(metadata)

    def registerTaskListUpdatedCallback(self, callback: Callable[[], None]) -> None:
        self.onTaskListUpdatedCallbacks.append(callback)

    def compare(self, list_a: list[ITaskModel], list_b: list[ITaskModel]) -> bool:
        if len(list_a) != len(list_b):
            return False
        for i in range(len(list_a)):
            if list_a[i] != list_b[i]:
                return False
        return True

    def _exportJson(self) -> bytearray:
        taskList = self.__getTaskList()
        jsonStr = self.__generateExportJson(taskList)
        return bytearray(jsonStr, "utf-8")

    def exportTasks(self, selectedFormat: str) -> bytearray:
        supportedFormats: dict[str, Callable[[], bytearray]] = {
            "json": self._exportJson,
        }

        return supportedFormats[selectedFormat]()

    def importTasks(self, selectedFormat: str) -> None:
        raise NotImplementedError("Importing tasks is not supported for ObsidianTaskProvider")

    def __generateExportJson(self, taskList: List[ITaskModel]) -> str:
        tasks: list[dict[str, str]] = []
        for task in taskList:
            taskDict = {
                "description": task.getDescription(),
                "context": task.getContext(),
                "start": str(task.getStart().as_int()),
                "due": str(task.getDue().as_int()),
                "severity": str(task.getSeverity()),
                "totalCost": str(task.getTotalCost().as_pomodoros()),
                "investedEffort": str(task.getInvestedEffort().as_pomodoros()),
                "status": str(task.getStatus()),
                "calm": str(task.getCalm())
            }
            tasks.append(taskDict)
        return json.dumps({
            "tasks": tasks
        }, indent=4)
