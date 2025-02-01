"""
TelegramReportingService.py
"""

import asyncio
import threading
import datetime

from time import sleep as sleepSync
from typing import Tuple, List

from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.IReportingService import IReportingService
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IFilter import IFilter
from .Interfaces.IScheduling import IScheduling
from .Interfaces.IStatisticsService import IStatisticsService
from .wrappers.interfaces.IUserCommService import IUserCommService
from .wrappers.TimeManagement import TimeAmount, TimePoint

# ITaskListWrapper.py
from abc import ABC, abstractmethod
class ITaskListManager(ABC):
    pass
# TaskListWrapper.py
class TelegramTaskListManager(ITaskListManager):
    
    def __init__(self, taskModelList: List[ITaskModel], heuristics : List[Tuple[str, IHeuristic]], filters : List[Tuple[str, IFilter]], tasksPerPage: int = 5):
        
        self.__taskModelList = taskModelList

        self.__selectedTask = None
        
        self.__heuristicList = heuristics
        self.__selectedHeuristic = heuristics[0]
        
        self.__filterList = filters
        self.__selectedFilter = filters[0]

        self.reset_pagination(tasksPerPage)
    
    @property
    def filtered_task_list(self) -> List[ITaskModel]:
        
        newTaskList : List[ITaskModel] = self.__taskModelList

        if len(self.__filterList) > 0:
            selectedFilter : IFilter = self.__selectedFilter[1]
            newTaskList = selectedFilter.filter(newTaskList)

        if len(self.__heuristicList) > 0:
            heuristic : IHeuristic = self.__selectedHeuristic[1]
            sortedTaskList : List[Tuple[ITaskModel, float]] = heuristic.sort(newTaskList)
            newTaskList = [task for task, _ in sortedTaskList]

        return newTaskList
    
    @property
    def selected_task(self) -> ITaskModel:
        return self.__selectedTask
    
    @selected_task.setter
    def selected_task(self, task: ITaskModel):
        self.__selectedTask = task

    def reset_pagination(self, tasksPerPage: int = 5):
        self.__taskListPage = 0
        self.__tasksPerPage = tasksPerPage

    def next_page(self):
        self.__taskListPage += 1
    
    def prior_page(self):
        if self.__taskListPage > 0:
            self.__taskListPage -= 1
    
    def select_task(self, taskId: int):
        offset = self.__taskListPage * self.__tasksPerPage
        if 0 <= taskId < len(self.__taskModelList):
            self.__selectedTask = self.__taskModelList[taskId + offset]
        else:
            self.__selectedTask = None

    def clear_selected_task(self):
        self.__selectedTask = None

    def search_tasks(self, searchTerms: List[str]):
        return TelegramTaskListManager([task for task in self.__taskModelList if any(term.lower() in task.getDescription().lower() for term in searchTerms)], [], [], self.__tasksPerPage)

    def render_task_list_str(self, interactive: bool = True) -> str:
        interactiveId = "/task_" if interactive else ""

        subTaskList = self.__taskModelList[self.__taskListPage * self.__tasksPerPage : (self.__taskListPage + 1) * self.__tasksPerPage]
        subTaskListDescriptions = [(f"{interactiveId}{i+1} : {task.getDescription()}") for i, task in enumerate(subTaskList)]

        taskListString = "\n".join(subTaskListDescriptions)
        if interactive:
            totalPages = (len(self.__taskModelList) + self.__tasksPerPage - 1) // self.__tasksPerPage
            taskListString += "\n\nPage " + str(self.__taskListPage + 1) + " of " + str(totalPages) + "\n"
            taskListString += "/next - Next page\n/previous - Previous page"
            taskListString += "\n\nselected /heuristic : " + self.__selectedHeuristic[0]
            taskListString += "\nselected /filter : " + self.__selectedFilter[1].getDescription()
        
        return taskListString
    
    def update_taskList(self, taskModelList: List[ITaskModel]):
        self.__taskModelList : List[ITaskModel] = taskModelList
        self.__correctSelectedTask()
    
    def __correctSelectedTask(self):
        if self.__selectedTask is not None:
            lastSelectedTask = self.__selectedTask
            for task in self.__taskModelList:
                if task.getDescription() == lastSelectedTask.getDescription():
                    self.__selectedTask = task
                    break

    

class TelegramReportingService(IReportingService):

    def __init__(self, bot : IUserCommService , taskProvider : ITaskProvider, scheduling : IScheduling, statiticsProvider : IStatisticsService, heuristics : List[Tuple[str, IHeuristic]], filters : List[Tuple[str, IFilter]], categories : list[dict], chatId: int = 0):
        # Private Attributes
        self.run = True
        self.bot = bot
        self.chatId = chatId
        self.taskProvider = taskProvider
        self.scheduling = scheduling
        self.statiticsProvider = statiticsProvider
        
        self.__lastModelList : List[ITaskModel] = []
        self._updateFlag = False
        
        self._lastWrapper = TelegramTaskListManager(self._lastRawList, heuristics, filters) #TODO: IoC
        
        self._lastError = "Event loop initialized"
        self._lock = threading.Lock()

        # TODO: Marked for removal
        self._lastRawList = self.taskProvider.getTaskList()

        # TODO: All the following fiels might be moved to a proper TaskListManager Class
        self._selectedTask = None
        self._lastOffset = None
        self._ignoreNextUpdate = False
        
        self._heuristicList = heuristics
        self._selectedHeuristicIndex = 0

        self._filterList = filters
        self._selectedFilterIndex = 0

        self._categories = categories
        pass

    def dispose(self):
        self.run = False
        self.bot.shutdown()
        self.taskProvider.dispose()
        pass

    def onTaskListUpdated(self):
        with self._lock:
            self._updateFlag = True
            if not self._ignoreNextUpdate:
                self._lastWrapper.update_taskList(self.taskProvider.getTaskList())
            else:
                self._ignoreNextUpdate = False

    def listenForEvents(self):
        self.taskProvider.registerTaskListUpdatedCallback(self.onTaskListUpdated)
        errCount = 0
        while self.run:
            try:
                asyncio.run(self._listenForEvents())
                errCount = 0
            except Exception as e:
                self._lastError = f"Error: {repr(e)}"
                print(self._lastError)
                sleepSync(10)
                errCount += 1
                if errCount > 30:
                    print("stopping container")
                    self.run = False
                    break
            

    async def _listenForEvents(self):
        await self.bot.initialize()
        await self.bot.sendMessage(chat_id=self.chatId, text=self._lastError)
        while self.run:
            try:
                await self.runEventLoop()
            except Exception as e:
                try:
                    await self.bot.shutdown()
                except Exception as e:
                    print(f"Fatal error: {repr(e)} shutting down.")
                    self.run = False
                finally:
                    raise e
    
    def hasFilteredListChanged(self):
        filteredList = self._lastWrapper.filtered_task_list
        if not self.taskProvider.compare(self._lastWrapper.filtered_task_list, self.__lastModelList):
            return False
        self.__lastModelList = filteredList
        return False
        

    async def checkFilteredListChanges(self):
        if self.chatId != 0 and self.hasFilteredListChanged():
            # Send the updated list
            nextTask = ""
            filteredList = self._lastWrapper.filtered_task_list
            if len(filteredList) != 0:
                nextTask = f"\n\n/task_1 : {filteredList[0].getDescription()}"
            self._lastWrapper.reset_pagination()
            await self.bot.sendMessage(chat_id=self.chatId, text="Task /list updated" + nextTask)

    async def runEventLoop(self):

        self.statiticsProvider.initialize()

        with self._lock:
            await self.checkFilteredListChanges()

        # Reads every message received by the bot
        result = await self.bot.getMessageUpdates()
            
        with self._lock:
            if result == None:
                return
            
            if self.chatId == 0:
                self.chatId = result[0]
            elif result[0] == int(self.chatId):
                await self.processMessage(result[1])

    async def sendHelp(self):
        helpMessage = "Commands:"
        helpMessage += "\n\t/list - List all tasks"
        helpMessage += "\n\t/heuristic - List heuristic options"
        helpMessage += "\n\t/filter - List filter options"
        helpMessage += "\n\t/new [description] - Create a new default task"
        helpMessage += "\n\t/schedule [expected work per day (optional)] - Reeschedules the selected task"
        helpMessage += "\n\t/stats - Show work done statistics"
        await self.bot.sendMessage(chat_id=self.chatId, text=helpMessage)

    # Each command must be made into an object and injected into this class
    async def listCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._lastWrapper.reset_pagination()
        await self.sendTaskList()

    async def nextCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._lastWrapper.next_page()
        if expectAnswer:
            await self.sendTaskList()

    async def previousCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._lastWrapper.prior_page()
        if expectAnswer:
            await self.sendTaskList()

    async def selectTaskCommand(self, messageText: str = "", expectAnswer: bool = True):
        taskId = int(messageText.split("_")[1]) - 1
        self._lastWrapper.select_task(taskId)
        
        selectedTask : ITaskModel = self._lastWrapper.get_selected_task()
        if expectAnswer:
            await self.sendTaskInformation(selectedTask)

    async def taskInfoCommand(self, messageText: str = "", expectAnswer: bool = True):
        if self._selectedTask is not None:
            await self.sendTaskInformation(self._selectedTask, True)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def helpCommand(self, messageText: str = "", expectAnswer: bool = True):
        await self.sendHelp()

    async def heuristicListCommand(self, messageText: str = "", expectAnswer: bool = True):
        heuristicList = "\n".join([f"/heuristic_{i+1} : {heuristic[0]}" for i, heuristic in enumerate(self._heuristicList)])
        heuristicList += "\n\n/filter - List filter options"
        await self.bot.sendMessage(chat_id=self.chatId, text=heuristicList)

    async def filterListCommand(self, messageText: str = "", expectAnswer: bool = True):
        filterList = "\n".join([f"/filter_{i+1} : {filter[0]}" for i, filter in enumerate(self._filterList)])
        filterList += "\n\n/heuristic - List heuristic options"
        await self.bot.sendMessage(chat_id=self.chatId, text=filterList)

    async def heuristicSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._selectedHeuristicIndex = int(messageText.split("_")[1]) - 1
        if expectAnswer:
            await self.sendTaskList()

    async def filterSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._selectedFilterIndex = int(messageText.split("_")[1]) - 1
        if expectAnswer:
            await self.sendTaskList()

    async def doneCommand(self, messageText: str = "", expectAnswer: bool = True):
        if self._selectedTask is not None:
            task = self._selectedTask
            task.setStatus("x")
            self.taskProvider.saveTask(task)
            self._ignoreNextUpdate = True
            if expectAnswer:
                await self.sendTaskList()
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def setCommand(self, messageText: str = "", expectAnswer: bool = True):
        if self._selectedTask is not None:
            task = self._selectedTask
            params = messageText.split(" ")[1:]
            if len(params) < 2:
                params[0] = "help"
                params[1] = "me"
            await self.processSetParam(task, params[0], " ".join(params[1:]) if len(params) > 2 else params[1])
            self.taskProvider.saveTask(task)
            # self._ignoreNextUpdate = True
            if expectAnswer:
                await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def newCommand(self, messageText: str = "", expectAnswer: bool = True):
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            extendedParams = " ".join(params).split(";")
            
            if len(extendedParams) == 3:
                self._selectedTask = self.taskProvider.createDefaultTask(extendedParams[0])
                self._selectedTask.setContext(extendedParams[1])
                self._selectedTask.setTotalCost(TimeAmount(extendedParams[2]))
            else:
                self._selectedTask = self.taskProvider.createDefaultTask(" ".join(params))
            
            self.taskProvider.saveTask(self._selectedTask)
            self._ignoreNextUpdate = True
            self._lastRawList.append(self._selectedTask)
            if expectAnswer:
                await self.sendTaskInformation(self._selectedTask)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no description provided.")

    async def scheduleCommand(self, messageText: str = "", expectAnswer: bool = True):
        params = messageText.split(" ")[1:]
        if self._selectedTask is not None:
            self.scheduling.schedule(self._selectedTask, params.pop() if len(params) > 0 else "")
            self.taskProvider.saveTask(self._selectedTask)
            if expectAnswer:
                await self.sendTaskInformation(self._selectedTask)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def workCommand(self, messageText: str = "", expectAnswer: bool = True):
        params = messageText.split(" ")[1:]
        if self._selectedTask is not None:
            task = self._selectedTask
            work_units = TimeAmount(" ".join(params[0:]))
            await self.processSetParam(task, "effort_invested", str(work_units.as_pomodoros()))
            self.taskProvider.saveTask(task)
            date = datetime.datetime.now().date()
            self.statiticsProvider.doWork(date, work_units.as_pomodoros())
            if expectAnswer:
                await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def statsCommand(self, messageText: str = "", expectAnswer: bool = True):
        statsMessage = "Work done in the last 7 days:\n"
        statsMessage += "`|    Date    | Work Done |`\n"
        statsMessage += "`|------------|-----------|`\n"
        totalWork : TimeAmount = TimeAmount("0")
        for i in range(7):
            date : TimePoint = TimePoint.today() + TimeAmount(f"-{i}d")
            workDone : TimeAmount = self.statiticsProvider.getWorkDone(date)
            totalWork += workDone
            statsMessage += f"`| {date} |    {round(workDone.as_pomodoros(), 1)}    |`\n"
        # add average work done per day
        statsMessage += "`|------------|-----------|`\n"
        statsMessage += f"`|   Average  |    {round(totalWork.as_pomodoros()/7, 1)}    |`\n"
        statsMessage += "`|------------|-----------|`\n\n"

        statsMessage += "Workload statistics:\n"
        workloadStats = self.statiticsProvider.getWorkloadStats(self._lastRawList)
        workload = workloadStats[0]
        remEffort = workloadStats[1]
        heuristicValue = workloadStats[2]
        heuristicName = workloadStats[3]
        offender = workloadStats[4]
        offenderMax = workloadStats[5]

        statsMessage += f"`current workload: {workload} per day`\n"
        statsMessage += f"    `max Offender: '{offender}' with {offenderMax} per day`\n"
        statsMessage += f"`total remaining effort: {remEffort}`\n"
        statsMessage += f"`max {heuristicName}: {heuristicValue}`\n\n"
        statsMessage += "/list - return back to the task list"

        await self.bot.sendMessage(chat_id=self.chatId, text=statsMessage, parse_mode="Markdown")

    async def snoozeCommand(self, messageText: str = "", expectAnswer: bool = True):
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            params = params[0]
        else:
            params = "5m"

        startParams = f"/set start now;+{params}"
        await self.setCommand(startParams)

    async def exportCommand(self, messageText: str = "", expectAnswer: bool = True):
        formatIds : dict = {
            "json": "json",
            #TODO: "ical": "ical"
        }
        
        messageArgs = messageText.split(" ")

        # message text contains the format of the export [json, ical]
        if len(messageArgs) > 1:
            exportFormat = messageArgs[1]
            selectedFormat = formatIds.get(exportFormat, "json")
        else:
            selectedFormat = "json"

        # get the exported data
        exportData : bytearray = self.taskProvider.exportTasks(selectedFormat)

        # send the exported data
        await self.bot.sendFile(chat_id=self.chatId, data=exportData)

    async def importCommand(self, messageText: str = "", expectAnswer: bool = True):
        formatIds : dict = {
            "json": "json",
            #TODO: "ical": "ical"
        }

        messageArgs = messageText.split(" ")

        # message text contains the format of the import [json, ical]
        if len(messageArgs) > 1:
            importFormat = messageArgs[1]
            selectedFormat = formatIds.get(importFormat, "json")
        else:
            selectedFormat = "json"

        # get the imported data
        self.taskProvider.importTasks(selectedFormat)
        self._lastRawList = self.taskProvider.getTaskList()
        await self.bot.sendMessage(chat_id=self.chatId, text=f"{selectedFormat} file imported", parse_mode="Markdown")
        await self.listCommand(messageText, expectAnswer)

    async def searchCommand(self, messageText: str = "", expectAnswer: bool = True):
        # getting results
        searchTerms = messageText.split(" ")[1:]
        searchResultsManager = self._lastWrapper.search_tasks(searchTerms)
        searchResults = searchResultsManager.filtered_task_list
        
        # processing results
        if len(searchResults) == 1:
            self._lastWrapper.selected_task = searchResults[0]
            await self.sendTaskInformation(searchResults[0])
        elif len(searchResults) > 0:
            taskListString = self._lastWrapper.render_task_list_str(False)
            await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="No results found")

    async def processMessage(self, messageText: str):
        commands : list[(str, function)] = [
            ("/list", self.listCommand),
            ("/next", self.nextCommand),
            ("/previous", self.previousCommand),
            ("/task_", self.selectTaskCommand),
            ("/info", self.taskInfoCommand),
            ("/heuristic_", self.heuristicSelectionCommand),
            ("/heuristic", self.heuristicListCommand),
            ("/filter_", self.filterSelectionCommand),
            ("/filter", self.filterListCommand),
            ("/done", self.doneCommand),
            ("/set", self.setCommand),
            ("/new", self.newCommand),
            ("/schedule", self.scheduleCommand),
            ("/work", self.workCommand),
            ("/stats", self.statsCommand),
            ("/snooze", self.snoozeCommand),
            ("/export", self.exportCommand),
            ("/import", self.importCommand),
            ("/search", self.searchCommand),
        ]

        messageTextLines = messageText.strip().splitlines()

        # get first command that starts with the messageText
        iteration = 0
        for message in messageTextLines:
            command = next((command for command in commands if message.startswith(command[0])), ("/help", self.helpCommand))[1]
            isLastIteration = iteration == len(messageTextLines) - 1
            await command(message, isLastIteration)
            iteration += 1

    def processRelativeTimeSet(self, current: TimePoint, value: str) -> TimePoint:
        values = value.split(";")
        currentTimePoint = current
        for value in values:
            if value == "now":
                currentTimePoint = currentTimePoint.now()
            elif value == "today":
                currentTimePoint = currentTimePoint.today()
            elif value == "tomorrow":
                currentTimePoint = currentTimePoint.tomorrow()
            else:
                currentTimePoint = currentTimePoint + TimeAmount(value)
        return currentTimePoint

    async def setDescriptionCommand(self, task: ITaskModel, value: str):
        task.setDescription(value)
        pass

    async def setContextCommand(self, task: ITaskModel, value: str):
        # check if context is equal to any of the categories prefixes throw error if not
        if any([value.startswith(category["prefix"]) for category in self._categories]):
            task.setContext(value)
        else:
            errorMessage = f"Invalid context {value}\nvalid contexts would be: {', '.join([category['prefix'] for category in self._categories])}"
            await self.bot.sendMessage(chat_id=self.chatId, text=errorMessage)

    async def setStartCommand(self, task: ITaskModel, value: str):
        if value.startswith("+") or value.startswith("-") or value.startswith("now") or value.startswith("today") or value.startswith("tomorrow"):
            start_timestamp = self.processRelativeTimeSet(task.getStart(), value)
            task.setStart(start_timestamp)
        else:
            start_datetime = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M')
            task.setStart(TimePoint(start_datetime))
        pass

    async def setDueCommand(self, task: ITaskModel, value: str):
        if value.startswith("+") or value.startswith("-") or value.startswith("today") or value.startswith("tomorrow"):
            due_timestamp = self.processRelativeTimeSet(task.getDue(), value)
            task.setDue(due_timestamp)
        else:
            due_datetime = datetime.datetime.strptime(value, '%Y-%m-%d')
            task.setDue(TimePoint(due_datetime))
        pass

    async def setSeverityCommand(self, task: ITaskModel, value: str):
        task.setSeverity(float(value))
        pass

    async def setTotalCostCommand(self, task: ITaskModel, value: str):
        task.setTotalCost(value)
        pass

    async def setEffortInvestedCommand(self, task: ITaskModel, value: str):
        newInvestedEffort = task.getInvestedEffort() + TimeAmount(value)
        newTotalCost = task.getTotalCost() - TimeAmount(value)
        task.setInvestedEffort(newInvestedEffort)
        task.setTotalCost(newTotalCost)
        pass

    async def setCalmCommand(self, task: ITaskModel, value: str):
        task.setCalm(value.upper().startswith("TRUE"))
        pass

    async def processSetParam(self, task: ITaskModel, param: str, value: str):

        commands : list[(str, function)] = [
            ("description", self.setDescriptionCommand),
            ("context", self.setContextCommand),
            ("start", self.setStartCommand),
            ("due", self.setDueCommand),
            ("severity", self.setSeverityCommand),
            ("total_cost", self.setTotalCostCommand),
            ("effort_invested", self.setEffortInvestedCommand),
            ("calm", self.setCalmCommand),
        ]

        command = next((command for command in commands if command[0].startswith(param)), ("", None))[1]
        if command is not None:
            await command(task, value)
        else:
            errorMessage = f"Invalid parameter {param}\nvalid parameters would be: description, context, start, due, severity, total_cost, effort_invested, calm"
            await self.bot.sendMessage(chat_id=self.chatId, text=errorMessage)

    async def sendTaskList(self, interactive : bool = True):
        self._lastWrapper.clear_selected_task()

        taskListString = self._lastWrapper.render_task_list_str(interactive)

        await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass

    async def sendTaskInformation(self, task: ITaskModel, extended : bool = False):
        taskDescription = task.getDescription()
        taskContext = task.getContext()
        taskSeverity = task.getSeverity()
        taskStartDate : TimePoint = task.getStart()
        taskDueDate : TimePoint = task.getDue()
        taskRemainingCost : TimeAmount = TimeAmount(f"{max(task.getTotalCost().as_pomodoros(), 0.0)}p")
        taskEffortInvested : float = max(task.getInvestedEffort().as_pomodoros(), 0)
        taskTotalCost = TimeAmount(f"{max(task.getTotalCost().as_pomodoros(), 0.0)+taskEffortInvested}p")
        
        taskInformation = f"Task: {taskDescription}\nContext: {taskContext}\nStart Date: {taskStartDate}\nDue Date: {taskDueDate}\nTotal Cost: {taskTotalCost}\nRemaining: {taskRemainingCost}\nSeverity: {taskSeverity}"
        
        if extended:
            for i, heuristic in enumerate(self._heuristicList):
                heuristicName, heuristicInstance = heuristic
                taskInformation += f"\n{heuristicName} : " + heuristicInstance.getComment(task)
            
            taskInformation += f"\n\n<b>Metadata:</b><code>{self.taskProvider.getTaskMetadata(task)}</code>"

        taskInformation += "\n\n/list - Return to list"
        taskInformation += "\n/done - Mark task as done"
        taskInformation += "\n/set [param] [value] - Set task parameter"
        taskInformation += "\n\tparameters: description, context, start, due, severity, total\\_cost, effort\\_invested, calm"
        taskInformation += "\n/work [work_units] - invest work units in the task"
        taskInformation += "\n/snooze - snooze the task for 5 minutes"
        taskInformation += "\n/info - Show extended information"

        await self.bot.sendMessage(chat_id=self.chatId, text=taskInformation, parse_mode="HTML")
