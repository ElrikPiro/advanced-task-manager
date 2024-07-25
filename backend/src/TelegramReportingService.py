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
        self._selectedTaskIndex = None
        self._lastOffset = None
        
        self._heuristicList = heuristics
        self._selectedHeuristicIndex = 0

        self._filterList = filters
        self._selectedFilterIndex = 0

        self._lastTaskList = self.taskProvider.getTaskList()
        
        self._lastError = "Event loop initialized"
        pass

    def listenForEvents(self):
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

    def compare(self, list1, list2):
        if len(list1) != len(list2):
            return False
        for i in range(len(list1)):
            if list1[i] != list2[i]:
                return False
        return True

    def listUpdated(self):
        newTaskList : List[ITaskModel] = self.taskProvider.getTaskList()

        if len(self._heuristicList) > 0:
            heuristic : IHeuristic = self._heuristicList[self._selectedHeuristicIndex][1]
            sortedTaskList : List[Tuple[ITaskModel, float]] = heuristic.sort(newTaskList)
            newTaskList = [task for task, _ in sortedTaskList]

        if len(self._filterList) > 0:
            filter : IFilter = self._filterList[self._selectedFilterIndex][1]
            newTaskList = filter.filter(newTaskList)

        if not self.compare(newTaskList, self._lastTaskList):
            self._lastTaskList = newTaskList
            return True
        return False

    async def runEventLoop(self):
        # Reads every message received by the bot
        coroutine = self.bot.getUpdates(limit=1, timeout=10, allowed_updates=['message'], offset=self._lastOffset)
        wasListUpdated = self.listUpdated()

        if wasListUpdated and self.chatId != 0:
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
            self._selectedTaskIndex = taskId
            await self.sendTaskInformation(taskId)
        elif messageText == "/heuristic":
            heuristicList = "\n".join([f"/heuristic_{i+1} : {heuristic[0]}" for i, heuristic in enumerate(self._heuristicList)])
            heuristicList += "\n\n/filter - List filter options"
            await self.bot.sendMessage(chat_id=self.chatId, text=heuristicList)
        elif messageText.startswith("/heuristic_"):
            self._selectedHeuristicIndex = int(messageText.split("_")[1]) - 1
            self.listUpdated()
            await self.sendTaskList()
        elif messageText == "/filter":
            filterList = "\n".join([f"/filter_{i+1} : {filter[0]}" for i, filter in enumerate(self._filterList)])
            filterList += "\n\n/heuristic - List heuristic options"
            await self.bot.sendMessage(chat_id=self.chatId, text=filterList)
        elif messageText.startswith("/filter_"):
            self._selectedFilterIndex = int(messageText.split("_")[1]) - 1
            self.listUpdated()
            await self.sendTaskList()
        elif messageText == "/done":
            if self._selectedTaskIndex is not None:
                task = self._lastTaskList[self._selectedTaskIndex]
                task.setStatus("x")
                await self.sendTaskList()
            else:
                await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")
        else:
            await self.sendHelp()
        try:
            await message.delete()
        except:
            pass
        pass

    async def sendTaskList(self):
        self._selectedTaskIndex = None

        subTaskList = self._lastTaskList[self._taskListPage * self._tasksPerPage : (self._taskListPage + 1) * self._tasksPerPage]
        subTaskListDescriptions = [(f"/task_{i+1} : {task.getDescription()}") for i, task in enumerate(subTaskList)]

        taskListString = "\n".join(subTaskListDescriptions)
        taskListString += "\n\nPage " + str(self._taskListPage + 1) + " of " + str(len(self._lastTaskList) // self._tasksPerPage + 1) + "\n"
        taskListString += "/next - Next page\n/previous - Previous page"
        taskListString += "\n\nselected /heuristic : " + self._heuristicList[self._selectedHeuristicIndex][0]
        taskListString += "\nselected /filter : " + self._filterList[self._selectedFilterIndex][0]
        await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass

    async def sendTaskInformation(self, taskId: int):
        task = self._lastTaskList[taskId]
        taskDescription = task.getDescription()
        taskContext = task.getContext()
        taskSeverity = task.getSeverity()
        taskStartDate = datetime.datetime.fromtimestamp(task.getStart() / 1e3).strftime("%Y-%m-%d %H:%M:%S")
        taskDueDate = datetime.datetime.fromtimestamp(task.getDue() / 1e3).strftime("%Y-%m-%d")
        taskRemainingCost = max(task.getTotalCost(), 0)
        
        taskInformation = f"Task: {taskDescription}\nContext: {taskContext}\nStart Date: {taskStartDate}\nDue Date: {taskDueDate}\nRemaining Cost: {taskRemainingCost}\nSeverity: {taskSeverity}"
        for i, heuristic in enumerate(self._heuristicList):
            heuristicName, heuristicInstance = heuristic
            taskInformation += f"\n{heuristicName} : " + str(heuristicInstance.evaluate(task))
        

        taskInformation += "\n\n/list - Return to list"
        taskInformation += "\n/done - Mark task as done"
        await self.bot.sendMessage(chat_id=self.chatId, text=taskInformation)