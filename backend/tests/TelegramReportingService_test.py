from typing import NoReturn
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from src.TelegramReportingService import TelegramReportingService


class TestTelegramReportingService(unittest.TestCase):

    def setUp(self):
        self.bot = MagicMock()
        self.taskProvider = MagicMock()
        self.scheduling = MagicMock()
        self.statisticsProvider = MagicMock()
        self.task_list_manager = MagicMock()
        self.categories = [{"prefix": "@test"}]
        self.projectManager = MagicMock()
        self.messageBuilder = MagicMock()
        self.user = MagicMock()
        
        self.bot.sendMessage = AsyncMock()
        self.bot.shutdown = AsyncMock()

        self.telegramReportingService = TelegramReportingService(
            bot=self.bot,
            taskProvider=self.taskProvider,
            scheduling=self.scheduling,
            statiticsProvider=self.statisticsProvider,
            task_list_manager=self.task_list_manager,
            categories=self.categories,
            projectManager=self.projectManager,
            messageBuilder=self.messageBuilder,
            user=self.user
        )

    def test_dispose(self) -> None:
        # Act
        self.telegramReportingService.dispose()
        
        # Assert
        self.bot.shutdown.assert_called_once()
        self.taskProvider.dispose.assert_called_once()
        # assert run is set to False
        self.assertFalse(self.telegramReportingService.run)

    def test_onTaskListUpdated(self) -> None:
        # Arrange
        mockTaskList = [MagicMock(), MagicMock()]
        self.taskProvider.getTaskList.return_value = mockTaskList

        # Act
        self.telegramReportingService.onTaskListUpdated()

        # Assert
        self.assertTrue(self.telegramReportingService._updateFlag)
        self.task_list_manager.update_taskList.assert_called_once_with(mockTaskList)

    def test_listenForEvents_normal(self) -> None:
        # Arrange
        def stop_after_first_call() -> None:
            self.telegramReportingService.run = False

        mockTaskList = [MagicMock(), MagicMock()]
        self.taskProvider.getTaskList.return_value = mockTaskList
        self.telegramReportingService._listenForEvents = AsyncMock(side_effect=stop_after_first_call)

        # Act
        self.telegramReportingService.listenForEvents()

        # Assert
        self.taskProvider.registerTaskListUpdatedCallback.assert_called_once_with(self.telegramReportingService.onTaskListUpdated)
        self.task_list_manager.update_taskList.assert_called_once_with(mockTaskList)
        self.telegramReportingService._listenForEvents.assert_awaited_once()

    def test_listenForEvents_exception(self) -> None:
        # Arrange
        def stop_after_first_call() -> NoReturn:
            self.telegramReportingService.MAX_ERRORS = 0  # To speed up the test
            self.telegramReportingService.ERROR_TIMEOUT = 0  # To speed up the test
            raise Exception("Test Exception")

        mockTaskList = [MagicMock(), MagicMock()]
        self.taskProvider.getTaskList.return_value = mockTaskList
        self.telegramReportingService._listenForEvents = AsyncMock(side_effect=stop_after_first_call)

        # Act
        self.telegramReportingService.listenForEvents()

        # Assert
        self.taskProvider.registerTaskListUpdatedCallback.assert_called_once_with(self.telegramReportingService.onTaskListUpdated)
        self.task_list_manager.update_taskList.assert_called_once_with(mockTaskList)
        self.telegramReportingService._listenForEvents.assert_awaited_once()
        

if __name__ == '__main__':
    unittest.main()
