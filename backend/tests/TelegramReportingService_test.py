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

    def test_internalListenForEvents_normal(self) -> None:
        # Arrange
        def _stop_after_first_call() -> None:
            self.telegramReportingService.run = False

        MockLastError = MagicMock()
        self.telegramReportingService._lastError = MockLastError
        self.telegramReportingService.runEventLoop = AsyncMock(side_effect=_stop_after_first_call)

        self.bot.initialize = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService._listenForEvents())

        # Assert
        self.bot.initialize.assert_awaited_once()

    def test_internalListenForEvents_exception(self) -> None:
        # Arrange
        def _stop_after_first_call() -> None:
            raise Exception("Test Exception")

        MockLastError = MagicMock()
        self.telegramReportingService._lastError = MockLastError
        self.telegramReportingService.runEventLoop = AsyncMock(side_effect=_stop_after_first_call)

        self.bot.initialize = AsyncMock()
        self.bot.shutdown = AsyncMock(side_effect=Exception("Shutdown Exception"))

        # Act
        try:
            asyncio.run(self.telegramReportingService._listenForEvents())
        except Exception:
            pass

        # Assert
        self.bot.initialize.assert_awaited_once()
        self.bot.shutdown.assert_awaited_once()
        
        self.assertFalse(self.telegramReportingService.run)

    def test_hasFilteredListChanged_no_change(self) -> None:
        # Arrange
        mockTaskList = [MagicMock()]
        self.telegramReportingService._taskListManager.filtered_task_list = mockTaskList
        self.telegramReportingService._TelegramReportingService__lastModelList = mockTaskList
        self.taskProvider.compare.return_value = True

        # Act
        result = self.telegramReportingService.hasFilteredListChanged()

        # Assert
        self.assertFalse(result)
        self.taskProvider.compare.assert_called_once_with(mockTaskList, mockTaskList)

    def test_hasFilteredListChanged_with_change(self) -> None:
        # Arrange
        mockTaskList1 = [MagicMock()]
        mockTaskList2 = [MagicMock(), MagicMock()]
        self.telegramReportingService._taskListManager.filtered_task_list = mockTaskList2
        self.telegramReportingService._TelegramReportingService__lastModelList = mockTaskList1
        self.taskProvider.compare.return_value = False

        # Act
        result = self.telegramReportingService.hasFilteredListChanged()

        # Assert
        self.assertTrue(result)
        self.taskProvider.compare.assert_called_once_with(mockTaskList2, mockTaskList1)
        self.assertEqual(self.telegramReportingService._TelegramReportingService__lastModelList, mockTaskList2)

    def test_listCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.listCommand())

        # Assert
        self.task_list_manager.reset_pagination.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_nextCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.nextCommand())

        # Assert
        self.task_list_manager.next_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_previousCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.previousCommand())

        # Assert
        self.task_list_manager.prior_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_selectTaskCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task

        # Act
        asyncio.run(self.telegramReportingService.selectTaskCommand("task_1"))

        # Assert
        self.task_list_manager.select_task.assert_called_once_with("task_1")
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)
    

if __name__ == '__main__':
    unittest.main()
