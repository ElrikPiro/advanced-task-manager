import asyncio
import datetime

import threading
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

class TelegramReportingService(IReportingService):

    def __init__(self, bot : IUserCommService , taskProvider : ITaskProvider, scheduling : IScheduling, statiticsProvider : IStatisticsService, heuristics : List[Tuple[str, IHeuristic]], filters : List[Tuple[str, IFilter]], chatId: int = 0):
        self.run = True
        self.bot = bot
        self.chatId = chatId
        self.taskProvider = taskProvider
        self.scheduling = scheduling
        self.statiticsProvider = statiticsProvider
        self._taskListPage = 0
        self._tasksPerPage = 5
        self._selectedTask = None
        self._lastOffset = None
        self._ignoreNextUpdate = False
        
        self._heuristicList = heuristics
        self._selectedHeuristicIndex = 0

        self._filterList = filters
        self._selectedFilterIndex = 0

        self._updateFlag = False
        self._lastTaskList = self.taskProvider.getTaskList()
        self._lastRawList = self.taskProvider.getTaskList()
        
        self._lastError = "Event loop initialized"
        self._lock = threading.Lock()
        pass

    def onTaskListUpdated(self):
        with self._lock:
            self._updateFlag = True
            if not self._ignoreNextUpdate:
                self.pullListUpdates()
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
                    exit(-1)
            

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

    def pullListUpdates(self):
        if not self._updateFlag:
            return False
        else:
            self._updateFlag = False
            self._lastRawList : List[ITaskModel] = self.taskProvider.getTaskList()
            if self._selectedTask is not None:
                lastSelectedTask = self._selectedTask
                for task in self._lastRawList:
                    if task.getDescription() == lastSelectedTask.getDescription():
                        self._selectedTask = task
                        break
            return True
    
    def doFilter(self):
        newTaskList : List[ITaskModel] = self._lastRawList

        if len(self._filterList) > 0:
            filter : IFilter = self._filterList[self._selectedFilterIndex][1]
            newTaskList = filter.filter(newTaskList)

        if len(self._heuristicList) > 0:
            heuristic : IHeuristic = self._heuristicList[self._selectedHeuristicIndex][1]
            sortedTaskList : List[Tuple[ITaskModel, float]] = heuristic.sort(newTaskList)
            newTaskList = [task for task, _ in sortedTaskList]

        if not self.taskProvider.compare(newTaskList, self._lastTaskList):
            self._lastTaskList = newTaskList
            return True
        return False

    async def checkFilteredListChanges(self):
        if self.chatId != 0 and self.doFilter():
            # Send the updated list
            nextTask = ""
            if len(self._lastTaskList) != 0:
                nextTask = f"\n\n/task_1 : {self._lastTaskList[0].getDescription()}"
            self._taskListPage = 0
            await self.bot.sendMessage(chat_id=self.chatId, text="Task /list updated" + nextTask)
            pass

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
    async def listCommand(self, messageText: str = ""):
        self._taskListPage = 0
        await self.sendTaskList()

    async def nextCommand(self, messageText: str = ""):
        self._taskListPage += 1
        await self.sendTaskList()

    async def previousCommand(self, messageText: str = ""):
        self._taskListPage -= 1
        await self.sendTaskList()

    async def selectTaskCommand(self, messageText: str = ""):
        taskId = self._taskListPage * self._tasksPerPage + int(messageText.split("_")[1]) - 1
        self._selectedTask = self._lastTaskList[taskId]
        await self.sendTaskInformation(self._selectedTask)

    async def taskInfoCommand(self, messageText: str = ""):
        if self._selectedTask is not None:
            await self.sendTaskInformation(self._selectedTask, True)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def helpCommand(self, messageText: str = ""):
        await self.sendHelp()

    async def heuristicListCommand(self, messageText: str = ""):
        heuristicList = "\n".join([f"/heuristic_{i+1} : {heuristic[0]}" for i, heuristic in enumerate(self._heuristicList)])
        heuristicList += "\n\n/filter - List filter options"
        await self.bot.sendMessage(chat_id=self.chatId, text=heuristicList)

    async def filterListCommand(self, messageText: str = ""):
        filterList = "\n".join([f"/filter_{i+1} : {filter[0]}" for i, filter in enumerate(self._filterList)])
        filterList += "\n\n/heuristic - List heuristic options"
        await self.bot.sendMessage(chat_id=self.chatId, text=filterList)

    async def heuristicSelectionCommand(self, messageText: str = ""):
        self._selectedHeuristicIndex = int(messageText.split("_")[1]) - 1
        self.doFilter()
        await self.sendTaskList()

    async def filterSelectionCommand(self, messageText: str = ""):
        self._selectedFilterIndex = int(messageText.split("_")[1]) - 1
        self.doFilter()
        await self.sendTaskList()

    async def doneCommand(self, messageText: str = ""):
        if self._selectedTask is not None:
            task = self._selectedTask
            task.setStatus("x")
            self.taskProvider.saveTask(task)
            self._ignoreNextUpdate = True
            self.doFilter()
            await self.sendTaskList()
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def setCommand(self, messageText: str = ""):
        if self._selectedTask is not None:
            task = self._selectedTask
            params = messageText.split(" ")[1:]
            if len(params) < 2:
                params[0] = "help"
                params[1] = "me"
            await self.processSetParam(task, params[0], " ".join(params[1:]) if len(params) > 2 else params[1])
            self.taskProvider.saveTask(task)
            # self._ignoreNextUpdate = True
            await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def newCommand(self, messageText: str = ""):
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            extendedParams = " ".join(params).split(";")
            
            if len(extendedParams) == 3:
                self._selectedTask = self.taskProvider.createDefaultTask(extendedParams[0])
                self._selectedTask.setContext(extendedParams[1])
                self._selectedTask.setTotalCost(float(extendedParams[2]))
            else:
                self._selectedTask = self.taskProvider.createDefaultTask(" ".join(params))
            
            self.taskProvider.saveTask(self._selectedTask)
            self._ignoreNextUpdate = True
            self._lastRawList.append(self._selectedTask)
            self.doFilter()
            await self.sendTaskInformation(self._selectedTask)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no description provided.")

    async def scheduleCommand(self, messageText: str = ""):
        params = messageText.split(" ")[1:]
        if self._selectedTask is not None:
            self.scheduling.schedule(self._selectedTask, params.pop() if len(params) > 0 else "")
            self.taskProvider.saveTask(self._selectedTask)
            # self._ignoreNextUpdate = True
            await self.sendTaskInformation(self._selectedTask)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def workCommand(self, messageText: str = ""):
        params = messageText.split(" ")[1:]
        if self._selectedTask is not None:
            task = self._selectedTask
            work_units_str = " ".join(params[0:])
            await self.processSetParam(task, "effort_invested", work_units_str)
            self.taskProvider.saveTask(task)
            work_units = float(params[0])
            date = datetime.datetime.now().date()
            self.statiticsProvider.doWork(date, work_units)
            await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def statsCommand(self, messageText: str = ""):
        statsMessage = "Work done in the last 7 days:\n"
        statsMessage += "`|    Date    | Work Done |`\n"
        statsMessage += "`|------------|-----------|`\n"
        totalWork = 0
        for i in range(7):
            date = datetime.datetime.now().date() - datetime.timedelta(days=i)
            workDone = self.statiticsProvider.getWorkDone(date)
            totalWork += workDone
            statsMessage += f"`| {date} |    {round(workDone, 1)}    |`\n"
        # add average work done per day
        statsMessage += "`|------------|-----------|`\n"
        statsMessage += f"`|   Average  |    {round(totalWork/7, 1)}    |`\n"

        await self.bot.sendMessage(chat_id=self.chatId, text=statsMessage, parse_mode="Markdown")

    async def snoozeCommand(self, messageText: str = ""):
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            params = params[0]
        else:
            params = "5m"
            
        startParams = f"/set start now;+{params}"
        await self.setCommand(startParams)

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
        ]

        # get first command that starts with the messageText
        command = next((command for command in commands if messageText.startswith(command[0])), ("/help", self.helpCommand))[1]
        await command(messageText)

    def processRelativeTimeSet(self, current: int, value: str):
        values = value.split(";")
        for value in values:
            if value == "now":
                current = int(datetime.datetime.now().timestamp() * 1000)
            elif value == "today":
                today = datetime.datetime.now()
                today = today.replace(hour=0, minute=0, second=0, microsecond=0)
                current = int(today.timestamp() * 1000)
            elif value == "tomorrow":
                tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
                tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                current = int(tomorrow.timestamp() * 1000)
            else:
                sign = 1 if value.startswith("+") else -1
                modifier = 1000
                if value.endswith("d"):
                    modifier *= 24 * 60 * 60
                elif value.endswith("h"):
                    modifier *= 60 * 60
                elif value.endswith("m"):
                    modifier *= 60
                elif value.endswith("w"):
                    modifier *= 7 * 24 * 60 * 60
                current = current + sign * int(value[1:-1]) * modifier
        return current

    async def setDescriptionCommand(self, task: ITaskModel, value: str):
        task.setDescription(value)
        pass

    async def setContextCommand(self, task: ITaskModel, value: str):
        task.setContext(value)
        pass

    async def setStartCommand(self, task: ITaskModel, value: str):
        if value.startswith("+") or value.startswith("-") or value.startswith("now") or value.startswith("today") or value.startswith("tomorrow"):
            start_timestamp = self.processRelativeTimeSet(task.getStart(), value)
            task.setStart(int(start_timestamp))
        else:
            start_datetime = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M')
            start_timestamp = int(start_datetime.timestamp() * 1000)
            task.setStart(int(start_timestamp))
        pass

    async def setDueCommand(self, task: ITaskModel, value: str):
        if value.startswith("+") or value.startswith("-") or value.startswith("today") or value.startswith("tomorrow"):
            due_timestamp = self.processRelativeTimeSet(task.getDue(), value)
            task.setDue(int(due_timestamp))
        else:
            due_datetime = datetime.datetime.strptime(value, '%Y-%m-%d')
            due_timestamp = int(due_datetime.timestamp() * 1000)
            task.setDue(int(due_timestamp))
        pass

    async def setSeverityCommand(self, task: ITaskModel, value: str):
        task.setSeverity(float(value))
        pass

    async def setTotalCostCommand(self, task: ITaskModel, value: str):
        task.setTotalCost(float(value))
        pass

    async def setEffortInvestedCommand(self, task: ITaskModel, value: str):
        newInvestedEffort = task.getInvestedEffort() + float(value)
        newTotalCost = task.getTotalCost() - float(value)
        task.setInvestedEffort(float(newInvestedEffort))
        task.setTotalCost(float(newTotalCost))
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

    async def sendTaskList(self):
        self._selectedTask = None

        subTaskList = self._lastTaskList[self._taskListPage * self._tasksPerPage : (self._taskListPage + 1) * self._tasksPerPage]
        subTaskListDescriptions = [(f"/task_{i+1} : {task.getDescription()}") for i, task in enumerate(subTaskList)]

        taskListString = "\n".join(subTaskListDescriptions)
        taskListString += "\n\nPage " + str(self._taskListPage + 1) + " of " + str(len(self._lastTaskList) // self._tasksPerPage + 1) + "\n"
        taskListString += "/next - Next page\n/previous - Previous page"
        taskListString += "\n\nselected /heuristic : " + self._heuristicList[self._selectedHeuristicIndex][0]
        taskListString += "\nselected /filter : " + self._filterList[self._selectedFilterIndex][1].getDescription()
        await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass

    async def sendTaskInformation(self, task: ITaskModel, extended : bool = False):
        taskDescription = task.getDescription()
        taskContext = task.getContext()
        taskSeverity = task.getSeverity()
        taskStartDate = datetime.datetime.fromtimestamp(task.getStart() / 1e3).strftime("%Y-%m-%d %H:%M:%S")
        taskDueDate = datetime.datetime.fromtimestamp(task.getDue() / 1e3).strftime("%Y-%m-%d")
        taskRemainingCost = max(task.getTotalCost(), 0)
        taskEffortInvested = max(task.getInvestedEffort(), 0)
        
        taskInformation = f"Task: {taskDescription}\nContext: {taskContext}\nStart Date: {taskStartDate}\nDue Date: {taskDueDate}\nRemaining Cost: {taskRemainingCost}/{taskRemainingCost+taskEffortInvested}\nSeverity: {taskSeverity}"
        
        if extended:
            for i, heuristic in enumerate(self._heuristicList):
                heuristicName, heuristicInstance = heuristic
                taskInformation += f"\n{heuristicName} : " + str(heuristicInstance.evaluate(task))
            
            taskInformation += f"\n\n<b>Metadata:</b><code>{self.taskProvider.getTaskMetadata(task)}</code>"

        taskInformation += "\n\n/list - Return to list"
        taskInformation += "\n/done - Mark task as done"
        taskInformation += "\n/set [param] [value] - Set task parameter"
        taskInformation += "\n\tparameters: description, context, start, due, severity, total\\_cost, effort\\_invested, calm"
        taskInformation += "\n/work [work_units] - invest work units in the task"
        taskInformation += "\n/info - Show extended information"

        await self.bot.sendMessage(chat_id=self.chatId, text=taskInformation, parse_mode="HTML")