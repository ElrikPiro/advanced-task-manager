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

        self._lastTaskList = self.taskProvider.getTaskList()

        self.bot.initialize()
        pass

    def listenForEvents(self):
        while self.run:
            self.runEventLoop()

    def wasListUpdated(self):
        newTaskList = self.taskProvider.getTaskList()
        if newTaskList != self._lastTaskList:
            self._lastTaskList = newTaskList
            return True
        return False

    def runEventLoop(self):
        # Reads every message received by the bot
        coroutine = self.bot.getUpdates(limit=1, timeout=10, allowed_updates=['message'])
        wasListUpdated = self.wasListUpdated()

        if wasListUpdated and self.chatId != 0:
            # Send the updated list
            self.bot.sendMessage(chat_id=self.chatId, text="Task list updated")
            pass

        result : Tuple[telegram.Update] = coroutine.result()
        message : telegram.Message = result[0].message

        if self.chatId == 0:
            self.chatId = message.chat.id
        elif message.chat.id == self.chatId:
            self.processMessage(message)

    def processMessage(self, message: telegram.Message):
        messageText = message.text
        if messageText == "/list":
            self.sendTaskList()
        elif messageText == "/exit":
            self.run = False
        elif messageText == "/next":
            self._taskListPage += 1
            self.sendTaskList()
        elif messageText == "/previous":
            self._taskListPage -= 1
            self.sendTaskList()
        pass

    def sendTaskList(self):
        subTaskList = self._lastTaskList[self._taskListPage * self._tasksPerPage : (self._taskListPage + 1) * self._tasksPerPage]
        taskListString = "\n".join(subTaskList)
        taskListString += "\n\nPage " + str(self._taskListPage + 1) + " of " + str(len(self._lastTaskList) // self._tasksPerPage + 1)
        self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass