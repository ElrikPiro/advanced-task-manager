import asyncio

from typing import Tuple
from .Interfaces.IReportingService import IReportingService
from .Interfaces.ITaskProvider import ITaskProvider
import telegram

class TelegramReportingService(IReportingService):

    def __init__(self, bot : telegram.Bot , taskProvider : ITaskProvider, chatId: int = 0):
        self.run = True
        self.bot = bot
        self.chatId = chatId
        self.taskProvider = taskProvider
        self._taskListPage = 0
        self._tasksPerPage = 5
        self._lastOffset = None

        self._lastTaskList = self.taskProvider.getTaskList()
        pass

    def listenForEvents(self):
        asyncio.run(self._listenForEvents())

    async def _listenForEvents(self):
        await self.bot.initialize()
        while self.run:
            await self.runEventLoop()

    def compare(self, list1, list2):
        if len(list1) != len(list2):
            return False
        for i in range(len(list1)):
            if list1[i] != list2[i]:
                return False
        return True

    def wasListUpdated(self):
        newTaskList = self.taskProvider.getTaskList()
        if not self.compare(newTaskList, self._lastTaskList):
            self._lastTaskList = newTaskList
            return True
        return False

    async def runEventLoop(self):
        # Reads every message received by the bot
        coroutine = self.bot.getUpdates(limit=1, timeout=10, allowed_updates=['message'], offset=self._lastOffset)
        wasListUpdated = self.wasListUpdated()

        if wasListUpdated and self.chatId != 0:
            # Send the updated list
            await self.bot.sendMessage(chat_id=self.chatId, text="Task list updated")
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
        helpMessage = "Commands:\n/list - List all tasks\n/next - Next page\n/previous - Previous page\n/exit - Exit"
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
        else:
            await self.sendHelp()
        try:
            await message.delete()
        except:
            pass
        pass

    async def sendTaskList(self):
        subTaskList = self._lastTaskList[self._taskListPage * self._tasksPerPage : (self._taskListPage + 1) * self._tasksPerPage]
        subTaskListDescriptions = [(f"{i+1}. {task.getDescription()}") for i, task in enumerate(subTaskList)]

        taskListString = "\n".join(subTaskListDescriptions)
        taskListString += "\n\nPage " + str(self._taskListPage + 1) + " of " + str(len(self._lastTaskList) // self._tasksPerPage + 1)
        await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass