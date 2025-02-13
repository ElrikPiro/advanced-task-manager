"""
TelegramReportingService.py
"""

import asyncio
import threading
import datetime

from time import sleep as sleepSync
from typing import List

from .Interfaces.ITaskListManager import ITaskListManager
from .Interfaces.IReportingService import IReportingService
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IScheduling import IScheduling
from .Interfaces.IStatisticsService import IStatisticsService
from .wrappers.interfaces.IUserCommService import IUserCommService
from .wrappers.TimeManagement import TimeAmount, TimePoint

class TelegramReportingService(IReportingService):

    def __init__(self, bot : IUserCommService , taskProvider : ITaskProvider, scheduling : IScheduling, statiticsProvider : IStatisticsService, task_list_manager : ITaskListManager, categories : list[dict], chatId: int = 0):
        # Private Attributes
        self.run = True
        self.bot = bot
        self.chatId = chatId
        self.taskProvider = taskProvider
        self.scheduling = scheduling
        self.statiticsProvider = statiticsProvider
        
        self.__lastModelList : List[ITaskModel] = []
        self._updateFlag = False
        
        self._taskListManager = task_list_manager
        
        self._lastError = "Event loop initialized"
        self._lock = threading.Lock()

        self._ignoreNextUpdate = False
        
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
            self._taskListManager.update_taskList(self.taskProvider.getTaskList())

    def listenForEvents(self):
        self.taskProvider.registerTaskListUpdatedCallback(self.onTaskListUpdated)
        self._taskListManager.update_taskList(self.taskProvider.getTaskList())
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
        filteredList = self._taskListManager.filtered_task_list
        if self.taskProvider.compare(self._taskListManager.filtered_task_list, self.__lastModelList):
            return False
        self.__lastModelList = filteredList
        return True
        

    async def checkFilteredListChanges(self):
        if self.chatId != 0 and self.hasFilteredListChanged():
            # Send the updated list
            nextTask = ""
            filteredList = self._taskListManager.filtered_task_list
            if len(filteredList) != 0:
                nextTask = f"\n\n/task_1 : {filteredList[0].getDescription()}"
            self._taskListManager.reset_pagination()
            if self._ignoreNextUpdate:
                self._ignoreNextUpdate = False
                return
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
        self._taskListManager.reset_pagination()
        await self.sendTaskList()

    async def nextCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.next_page()
        if expectAnswer:
            await self.sendTaskList()

    async def previousCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.prior_page()
        if expectAnswer:
            await self.sendTaskList()

    async def selectTaskCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.select_task(messageText)
        
        selectedTask : ITaskModel = self._taskListManager.selected_task
        if expectAnswer:
            await self.sendTaskInformation(selectedTask)

    async def taskInfoCommand(self, messageText: str = "", expectAnswer: bool = True):
        selectedTask = self._taskListManager.selected_task
        if selectedTask is not None:
            await self.sendTaskInformation(selectedTask, True)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def helpCommand(self, messageText: str = "", expectAnswer: bool = True):
        await self.sendHelp()

    async def heuristicListCommand(self, messageText: str = "", expectAnswer: bool = True):
        await self.bot.sendMessage(chat_id=self.chatId, text=self._taskListManager.get_heuristic_list())

    async def filterListCommand(self, messageText: str = "", expectAnswer: bool = True):
        filterList = self._taskListManager.get_filter_list()
        await self.bot.sendMessage(chat_id=self.chatId, text=filterList)

    async def heuristicSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.select_heuristic(messageText)
        if expectAnswer:
            await self.sendTaskList()

    async def filterSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.select_filter(messageText)
        if expectAnswer:
            await self.sendTaskList()

    async def doneCommand(self, messageText: str = "", expectAnswer: bool = True):
        selected_task = self._taskListManager.selected_task
        if selected_task is not None:
            task = selected_task
            task.setStatus("x")
            self.taskProvider.saveTask(task)
            self._ignoreNextUpdate = True
            if expectAnswer:
                await self.sendTaskList()
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def setCommand(self, messageText: str = "", expectAnswer: bool = True):
        selected_task = self._taskListManager.selected_task
        if selected_task is not None:
            task = selected_task
            params = messageText.split(" ")[1:]
            if len(params) < 2:
                params[0] = "help"
                params[1] = "me"
            await self.processSetParam(task, params[0], " ".join(params[1:]) if len(params) > 2 else params[1])
            self.taskProvider.saveTask(task)
            self._ignoreNextUpdate = True
            if expectAnswer:
                await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def newCommand(self, messageText: str = "", expectAnswer: bool = True):
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            extendedParams = " ".join(params).split(";")
            
            if len(extendedParams) == 3:
                self._taskListManager.selected_task = self.taskProvider.createDefaultTask(extendedParams[0])
                selected_task = self._taskListManager.selected_task
                selected_task.setContext(extendedParams[1])
                selected_task.setTotalCost(TimeAmount(extendedParams[2]))
            else:
                self._taskListManager.selected_task = self.taskProvider.createDefaultTask(" ".join(params))
                selected_task = self._taskListManager.selected_task
            
            self.taskProvider.saveTask(selected_task)
            self._ignoreNextUpdate = True
            self._taskListManager.add_task(selected_task)
            if expectAnswer:
                await self.sendTaskInformation(selected_task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no description provided.")

    async def scheduleCommand(self, messageText: str = "", expectAnswer: bool = True):
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            self.scheduling.schedule(selected_task, params.pop() if len(params) > 0 else "")
            self.taskProvider.saveTask(selected_task)
            if expectAnswer:
                await self.sendTaskInformation(selected_task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def workCommand(self, messageText: str = "", expectAnswer: bool = True):
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            task = selected_task
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
        await self.bot.sendMessage(chat_id=self.chatId, text=self._taskListManager.get_list_stats(), parse_mode="Markdown")

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
        self._taskListManager.update_taskList(self.taskProvider.getTaskList())
        await self.bot.sendMessage(chat_id=self.chatId, text=f"{selectedFormat} file imported", parse_mode="Markdown")
        await self.listCommand(messageText, expectAnswer)

    async def searchCommand(self, messageText: str = "", expectAnswer: bool = True):
        # getting results
        searchTerms = messageText.split(" ")[1:]
        searchResultsManager = self._taskListManager.search_tasks(searchTerms)
        searchResults = searchResultsManager.filtered_task_list
        
        # processing results
        if len(searchResults) == 1:
            self._taskListManager.selected_task = searchResults[0]
            await self.sendTaskInformation(searchResults[0])
        elif len(searchResults) > 0:
            taskListString = searchResultsManager.render_task_list_str(False)
            await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="No results found")

    async def agendaCommand(self, messageText: str = "", expectAnswer: bool = True):
        agenda = self._taskListManager.render_day_agenda(TimePoint.today(), self._categories)
        await self.bot.sendMessage(chat_id=self.chatId, text=agenda)

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
            ("/agenda", self.agendaCommand),
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
        self._taskListManager.clear_selected_task()

        taskListString = self._taskListManager.render_task_list_str(interactive)

        await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass

    async def sendTaskInformation(self, task: ITaskModel, extended : bool = False):
        taskInformation = self._taskListManager.render_task_information(task, self.taskProvider, extended)

        await self.bot.sendMessage(chat_id=self.chatId, text=taskInformation, parse_mode="HTML")
