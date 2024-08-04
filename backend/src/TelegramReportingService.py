import asyncio
import datetime

from time import sleep as sleepSync
from typing import Tuple, List
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.IReportingService import IReportingService
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IFilter import IFilter
import telegram

class TelegramReportingService(IReportingService):

    def __init__(self, bot : telegram.Bot , taskProvider : ITaskProvider, heuristics : List[Tuple[str, IHeuristic]], filters : List[Tuple[str, IFilter]], chatId: int = 0):
        self.run = True
        self.bot = bot
        self.chatId = chatId
        self.taskProvider = taskProvider
        self._taskListPage = 0
        self._tasksPerPage = 5
        self._selectedTask = None
        self._lastOffset = None
        
        self._heuristicList = heuristics
        self._selectedHeuristicIndex = 0

        self._filterList = filters
        self._selectedFilterIndex = 0

        self._updateFlag = False
        self._lastTaskList = self.taskProvider.getTaskList()
        self._lastRawList = self.taskProvider.getTaskList()
        
        self._lastError = "Event loop initialized"
        pass

    def onTaskListUpdated(self):
        self._updateFlag = True

    def listenForEvents(self):
        self.taskProvider.registerTaskListUpdatedCallback(self.onTaskListUpdated)
        while self.run:
            try:
                asyncio.run(self._listenForEvents())
            except Exception as e:
                self._lastError = f"Error: {repr(e)}"
                print(self._lastError)
                sleepSync(10)
            

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

    async def runEventLoop(self):
        # Reads every message received by the bot
        coroutine = self.bot.getUpdates(limit=1, timeout=10, allowed_updates=['message'], offset=self._lastOffset)
        self.pullListUpdates()

        if self.chatId != 0 and self.doFilter():
            # Send the updated list
            nextTask = ""
            if len(self._lastTaskList) != 0:
                nextTask = f"\n\n/task_1 : {self._lastTaskList[0].getDescription()}"
            self._taskListPage = 0
            await self.bot.sendMessage(chat_id=self.chatId, text="Task /list updated" + nextTask)
            pass

        result : Tuple[telegram.Update] = await coroutine
        if len(result) == 0:
            return
        
        self._lastOffset = result[0].update_id + 1
        message : telegram.Message = result[0].message

        if self.chatId == 0:
            self.chatId = message.chat.id
        elif message.chat.id == int(self.chatId):
            await self.processMessage(message)

    async def sendHelp(self):
        helpMessage = "Commands:"
        helpMessage += "\n\t/list - List all tasks"
        helpMessage += "\n\t/heuristic - List heuristic options"
        helpMessage += "\n\t/filter - List filter options"
        helpMessage += "\n\t/new [description] - Create a new default task"
        await self.bot.sendMessage(chat_id=self.chatId, text=helpMessage)

    async def processMessage(self, message: telegram.Message):
        messageText = message.text
        if messageText == "/list":
            self._taskListPage = 0
            await self.sendTaskList()
        elif messageText == "/next":
            self._taskListPage += 1
            await self.sendTaskList()
        elif messageText == "/previous":
            self._taskListPage -= 1
            await self.sendTaskList()
        elif messageText.startswith("/task_"):
            taskId = self._taskListPage * self._tasksPerPage + int(messageText.split("_")[1]) - 1
            self._selectedTask = self._lastTaskList[taskId]
            await self.sendTaskInformation(self._selectedTask)
        elif messageText == "/heuristic":
            heuristicList = "\n".join([f"/heuristic_{i+1} : {heuristic[0]}" for i, heuristic in enumerate(self._heuristicList)])
            heuristicList += "\n\n/filter - List filter options"
            await self.bot.sendMessage(chat_id=self.chatId, text=heuristicList)
        elif messageText.startswith("/heuristic_"):
            self._selectedHeuristicIndex = int(messageText.split("_")[1]) - 1
            self.doFilter()
            await self.sendTaskList()
        elif messageText == "/filter":
            filterList = "\n".join([f"/filter_{i+1} : {filter[0]}" for i, filter in enumerate(self._filterList)])
            filterList += "\n\n/heuristic - List heuristic options"
            await self.bot.sendMessage(chat_id=self.chatId, text=filterList)
        elif messageText.startswith("/filter_"):
            self._selectedFilterIndex = int(messageText.split("_")[1]) - 1
            self.doFilter()
            await self.sendTaskList()
        elif messageText == "/done":
            if self._selectedTask is not None:
                task = self._selectedTask
                task.setStatus("x")
                self.taskProvider.saveTask(task)
                self.doFilter()
                await self.sendTaskList()
            else:
                await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")
        elif messageText.startswith("/set"):
            if self._selectedTask is not None:
                task = self._selectedTask
                params = messageText.split(" ")[1:]
                if len(params) < 2:
                    params[0] = "help"
                    params[1] = "me"
                await self.processSetParam(task, params[0], " ".join(params[1:]) if len(params) > 2 else params[1])
                self.taskProvider.saveTask(task)
                await self.sendTaskInformation(task)
            else:
                await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")
        elif messageText.startswith("/new"):
            params = messageText.split(" ")[1:]
            if len(params) > 0:
                self._selectedTask = self.taskProvider.createDefaultTask(" ".join(params))
                self._lastRawList.append(self._selectedTask)
                self.doFilter()
                await self.sendTaskInformation(self._selectedTask)
            else:
                await self.bot.sendMessage(chat_id=self.chatId, text="no description provided.")
        else:
            await self.sendHelp()

    async def processSetParam(self, task: ITaskModel, param: str, value: str):
        if param == "description":
            task.setDescription(value)
            pass
        elif param == "context":
            task.setContext(value)
        elif param == "start":
            start_datetime = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M')
            start_timestamp = int(start_datetime.timestamp() * 1000)
            task.setStart(int(start_timestamp))
        elif param == "due":
            due_datetime = datetime.datetime.strptime(value, '%Y-%m-%d')
            due_timestamp = int(due_datetime.timestamp() * 1000)
            task.setDue(int(due_timestamp))
        elif param == "severity":
            task.setSeverity(float(value))
        elif param == "total_cost":
            task.setTotalCost(float(value))
        elif param == "effort_invested":
            newInvestedEffort = task.getInvestedEffort() + float(value)
            newTotalCost = task.getTotalCost() - float(value)
            task.setInvestedEffort(float(newInvestedEffort))
            task.setTotalCost(float(newTotalCost))
        elif param == "calm":
            task.setCalm(value.upper().startswith("TRUE"))
        else:
            errorMessage = f"Invalid parameter {param}\nvalid parameters would be: description, context, start, due, severity, total_cost, effort_invested, calm"
            await self.bot.sendMessage(chat_id=self.chatId, text=errorMessage)
        pass

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

    async def sendTaskInformation(self, task: ITaskModel):
        taskDescription = task.getDescription()
        taskContext = task.getContext()
        taskSeverity = task.getSeverity()
        taskStartDate = datetime.datetime.fromtimestamp(task.getStart() / 1e3).strftime("%Y-%m-%d %H:%M:%S")
        taskDueDate = datetime.datetime.fromtimestamp(task.getDue() / 1e3).strftime("%Y-%m-%d")
        taskRemainingCost = max(task.getTotalCost(), 0)
        taskEffortInvested = max(task.getInvestedEffort(), 0)
        
        taskInformation = f"Task: {taskDescription}\nContext: {taskContext}\nStart Date: {taskStartDate}\nDue Date: {taskDueDate}\nRemaining Cost: {taskRemainingCost}/{taskRemainingCost+taskEffortInvested}\nSeverity: {taskSeverity}"
        for i, heuristic in enumerate(self._heuristicList):
            heuristicName, heuristicInstance = heuristic
            taskInformation += f"\n{heuristicName} : " + str(heuristicInstance.evaluate(task))
        
        taskInformation += f"\n\n<b>Metadata:</b><code>{self.taskProvider.getTaskMetadata(task)}</code>"

        taskInformation += "\n\n/list - Return to list"
        taskInformation += "\n/done - Mark task as done"
        taskInformation += "\n/set [param] [value] - Set task parameter"
        taskInformation += "\n\tparameters: description, context, start, due, severity, total\\_cost, effort\\_invested, calm"
        await self.bot.sendMessage(chat_id=self.chatId, text=taskInformation, parse_mode="HTML")