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

    def test_checkFilteredListChanges_no_change(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 123
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=False)

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_called_once()
        self.bot.sendMessage.assert_not_awaited()

    def test_checkFilteredListChanges_with_change(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 123
        mock_task = MagicMock()
        mock_task.getProject.return_value = "test_project"
        mock_task.getDescription.return_value = "test_description"
        mock_task.getContext.return_value = "test_context"
        
        filtered_list = [mock_task]
        self.task_list_manager.filtered_task_list = filtered_list
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.messageBuilder.createOutboundMessage = MagicMock(return_value=MagicMock())

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_called_once()
        self.task_list_manager.reset_pagination.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_checkFilteredListChanges_chat_id_zero(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 0
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_not_called()
        self.bot.sendMessage.assert_not_awaited()

    def test_runEventLoop_no_messages(self) -> None:
        # Arrange
        self.bot.getMessageUpdates = AsyncMock(return_value=[])
        self.telegramReportingService.checkFilteredListChanges = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.runEventLoop())

        # Assert
        self.statisticsProvider.initialize.assert_called_once()
        self.telegramReportingService.checkFilteredListChanges.assert_awaited_once()
        self.bot.getMessageUpdates.assert_awaited_once()

    def test_runEventLoop_with_messages_valid_chat(self) -> None:
        # Arrange
        mock_message = MagicMock()
        mock_message.source.id = "123"
        messages = [mock_message]
        
        self.bot.getMessageUpdates = AsyncMock(return_value=messages)
        self.telegramReportingService.checkFilteredListChanges = AsyncMock()
        self.telegramReportingService.processMessage = AsyncMock()
        self.telegramReportingService.chatId = 123

        # Act
        asyncio.run(self.telegramReportingService.runEventLoop())

        # Assert
        self.statisticsProvider.initialize.assert_called_once()
        self.telegramReportingService.processMessage.assert_awaited_once_with(mock_message, True)

    def test_runEventLoop_with_messages_new_chat(self) -> None:
        # Arrange
        mock_message = MagicMock()
        mock_message.source.id = 456
        messages = [mock_message]
        
        self.bot.getMessageUpdates = AsyncMock(return_value=messages)
        self.telegramReportingService.checkFilteredListChanges = AsyncMock()
        self.telegramReportingService.processMessage = AsyncMock()
        self.telegramReportingService.chatId = 0

        # Act
        asyncio.run(self.telegramReportingService.runEventLoop())

        # Assert
        self.statisticsProvider.initialize.assert_called_once()
        self.assertEqual(self.telegramReportingService.chatId, 456)
        self.telegramReportingService.processMessage.assert_not_awaited()

    def test_taskInfoCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.taskInfoCommand())

        # Assert
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, True)

    def test_taskInfoCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.taskInfoCommand())

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("No task selected.")

    def test_helpCommand_no_args(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_helpCommand_specific_command(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help list"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_helpCommand_date_help(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help date"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_helpCommand_time_help(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help time"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_heuristicListCommand(self) -> None:
        # Arrange
        mock_heuristic_list = {"test": "heuristic"}
        self.task_list_manager.get_heuristic_list.return_value = mock_heuristic_list
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.heuristicListCommand())

        # Assert
        self.task_list_manager.get_heuristic_list.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_algorithmListCommand(self) -> None:
        # Arrange
        mock_algorithm_list = {"test": "algorithm"}
        self.task_list_manager.get_algorithm_list.return_value = mock_algorithm_list
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.algorithmListCommand())

        # Assert
        self.task_list_manager.get_algorithm_list.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_filterListCommand(self) -> None:
        # Arrange
        mock_filter_list = {"test": "filter"}
        self.task_list_manager.get_filter_list.return_value = mock_filter_list
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.filterListCommand())

        # Assert
        self.task_list_manager.get_filter_list.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_heuristicSelectionCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.heuristicSelectionCommand("test_heuristic"))

        # Assert
        self.task_list_manager.select_heuristic.assert_called_once_with("test_heuristic")
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_algorithmSelectionCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.algorithmSelectionCommand("test_algorithm"))

        # Assert
        self.task_list_manager.select_algorithm.assert_called_once_with("test_algorithm")
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_filterSelectionCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.filterSelectionCommand("test_filter"))

        # Assert
        self.task_list_manager.select_filter.assert_called_once_with("test_filter")
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_doneCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand())

        # Assert
        mock_task.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_doneCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand())

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task selected.")

    def test_setCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.setCommand("/set description test description"))

        # Assert
        self.telegramReportingService.processSetParam.assert_awaited_once_with(mock_task, "description", "test description")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)

    def test_setCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.setCommand("/set description test"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task selected.")

    def test_setCommand_with_two_params(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act - Test with proper parameters
        asyncio.run(self.telegramReportingService.setCommand("/set description test_value"))

        # Assert
        self.telegramReportingService.processSetParam.assert_awaited_once()
        self.taskProvider.saveTask.assert_called_once_with(mock_task)

    def test_newCommand_with_description(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.taskProvider.createDefaultTask.return_value = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new test task"))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("test task")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.task_list_manager.add_task.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)

    def test_newCommand_with_extended_params(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.taskProvider.createDefaultTask.return_value = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new test task;@context;2h"))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("test task")
        mock_task.setContext.assert_called_once_with("@context")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.task_list_manager.add_task.assert_called_once_with(mock_task)

    def test_newCommand_no_description(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no description provided.")

    def test_scheduleCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2h"))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_task, "2h")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)

    def test_scheduleCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2h"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task provided.")

    def test_workCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.workCommand("/work 1h"))

        # Assert
        self.telegramReportingService.processSetParam.assert_awaited_once()
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.statisticsProvider.doWork.assert_called_once()
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)

    def test_workCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.workCommand("/work 1h"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task provided.")

    def test_statsCommand(self) -> None:
        # Arrange
        mock_stats = {"test": "stats"}
        self.task_list_manager.get_list_stats.return_value = mock_stats
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.statsCommand())

        # Assert
        self.task_list_manager.get_list_stats.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_snoozeCommand_default_time(self) -> None:
        # Arrange
        self.telegramReportingService.setCommand = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.snoozeCommand("/snooze"))

        # Assert
        self.telegramReportingService.setCommand.assert_awaited_once_with("/set start now;+5m")

    def test_snoozeCommand_custom_time(self) -> None:
        # Arrange
        self.telegramReportingService.setCommand = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.snoozeCommand("/snooze 10m"))

        # Assert
        self.telegramReportingService.setCommand.assert_awaited_once_with("/set start now;+10m")

    def test_exportCommand_default_format(self) -> None:
        # Arrange
        mock_data = bytearray(b"test data")
        self.taskProvider.exportTasks.return_value = mock_data
        self.bot.sendFile = AsyncMock()
        self.telegramReportingService.chatId = 123

        # Act
        asyncio.run(self.telegramReportingService.exportCommand("/export"))

        # Assert
        self.taskProvider.exportTasks.assert_called_once_with("json")
        self.bot.sendFile.assert_awaited_once_with(chat_id=123, data=mock_data)

    def test_exportCommand_specific_format(self) -> None:
        # Arrange
        mock_data = bytearray(b"test data")
        self.taskProvider.exportTasks.return_value = mock_data
        self.bot.sendFile = AsyncMock()
        self.telegramReportingService.chatId = 123

        # Act
        asyncio.run(self.telegramReportingService.exportCommand("/export json"))

        # Assert
        self.taskProvider.exportTasks.assert_called_once_with("json")
        self.bot.sendFile.assert_awaited_once_with(chat_id=123, data=mock_data)

    def test_importCommand_default_format(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        self.telegramReportingService.listCommand = AsyncMock()
        mock_task_list = [MagicMock()]
        self.taskProvider.getTaskList.return_value = mock_task_list

        # Act
        asyncio.run(self.telegramReportingService.importCommand("/import"))

        # Assert
        self.taskProvider.importTasks.assert_called_once_with("json")
        self.task_list_manager.update_taskList.assert_called_once_with(mock_task_list)
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()
        self.telegramReportingService.listCommand.assert_awaited_once()

    def test_searchCommand_single_result(self) -> None:
        # Arrange
        mock_task = MagicMock()
        mock_manager = MagicMock()
        mock_manager.filtered_task_list = [mock_task]
        self.task_list_manager.search_tasks.return_value = mock_manager
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.searchCommand("/search test"))

        # Assert
        self.task_list_manager.search_tasks.assert_called_once_with(["test"])
        self.assertEqual(self.task_list_manager.selected_task, mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)

    def test_searchCommand_multiple_results(self) -> None:
        # Arrange
        from src.Utils import TaskListContent
        mock_tasks = [MagicMock(), MagicMock()]
        mock_manager = MagicMock()
        mock_manager.filtered_task_list = mock_tasks
        mock_content = TaskListContent(
            algorithm_name="test_algorithm",
            algorithm_desc="test description",
            sort_heuristic="test_heuristic",
            tasks=[],
            total_tasks=2,
            current_page=1,
            total_pages=1,
            active_filters=[],
            interactive=True
        )
        mock_manager.get_task_list_content.return_value = mock_content
        self.task_list_manager.search_tasks.return_value = mock_manager
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.searchCommand("/search test"))

        # Assert
        self.task_list_manager.search_tasks.assert_called_once_with(["test"])
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_searchCommand_no_results(self) -> None:
        # Arrange
        mock_manager = MagicMock()
        mock_manager.filtered_task_list = []
        self.task_list_manager.search_tasks.return_value = mock_manager
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.searchCommand("/search nonexistent"))

        # Assert
        self.task_list_manager.search_tasks.assert_called_once_with(["nonexistent"])
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("No results found")

    def test_agendaCommand(self) -> None:
        # Arrange
        mock_agenda = {"agenda": "content"}
        self.task_list_manager.get_day_agenda_content.return_value = mock_agenda
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.agendaCommand())

        # Assert
        self.task_list_manager.get_day_agenda_content.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_projectCommand_no_command(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.projectCommand("/project"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("No project command provided")

    def test_projectCommand_invalid_command(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.projectCommand("/project invalid"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("Invalid project command")

    def test_processMessage_calls_handler(self) -> None:
        # Arrange - Test that processMessage method exists and can be called
        mock_message = MagicMock()
        mock_message.content = {"command": "test", "args": []}

        # Act - Just verify the method runs without errors
        try:
            asyncio.run(self.telegramReportingService.processMessage(mock_message, True))
            success = True
        except Exception:
            success = False

        # Assert - Method should execute without throwing exceptions
        self.assertTrue(success)

    def test_processMessage_unknown_command(self) -> None:
        # Arrange
        mock_message = MagicMock()
        mock_message.content = {"command": "unknown", "args": []}
        self.telegramReportingService.helpCommand = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.processMessage(mock_message, True))

        # Assert
        self.telegramReportingService.helpCommand.assert_awaited_once_with("/unknown", True)

    def test_sendTaskList(self) -> None:
        # Arrange
        from src.Utils import TaskListContent
        mock_content = TaskListContent(
            algorithm_name="test_algorithm",
            algorithm_desc="test description",
            sort_heuristic="test_heuristic",
            tasks=[],
            total_tasks=0,
            current_page=1,
            total_pages=1,
            active_filters=[],
            interactive=True
        )
        self.task_list_manager.get_task_list_content.return_value = mock_content
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskList())

        # Assert
        self.task_list_manager.clear_selected_task.assert_called_once()
        self.task_list_manager.get_task_list_content.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_sendTaskInformation(self) -> None:
        # Arrange
        mock_task = MagicMock()
        mock_info = {"task": "info"}
        self.task_list_manager.get_task_information.return_value = mock_info
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskInformation(mock_task))

        # Assert
        self.task_list_manager.get_task_information.assert_called_once_with(mock_task, self.taskProvider, False)
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_sendTaskInformation_extended(self) -> None:
        # Arrange
        mock_task = MagicMock()
        mock_info = {"task": "extended_info"}
        self.task_list_manager.get_task_information.return_value = mock_info
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskInformation(mock_task, True))

        # Assert
        self.task_list_manager.get_task_information.assert_called_once_with(mock_task, self.taskProvider, True)
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_processRelativeTimeSet_now(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "now")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_today(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "today")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_tomorrow(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "tomorrow")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_time_format(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "14:30")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_multiple_values(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "today;+2h")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_setDescriptionCommand(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setDescriptionCommand(mock_task, "New Description"))
        
        # Assert
        mock_task.setDescription.assert_called_once_with("New Description")

    def test_setContextCommand_valid_context(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setContextCommand(mock_task, "@test_context"))
        
        # Assert
        mock_task.setContext.assert_called_once_with("@test_context")

    def test_setContextCommand_invalid_context(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setContextCommand(mock_task, "invalid_context"))
        
        # Assert
        mock_task.setContext.assert_not_called()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_setStartCommand_relative_format(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        mock_task = MagicMock()
        mock_task.getStart.return_value = TimePoint.now()
        
        # Act
        asyncio.run(self.telegramReportingService.setStartCommand(mock_task, "+2h"))
        
        # Assert
        mock_task.setStart.assert_called_once()

    def test_setStartCommand_absolute_format_error_handling(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act & Assert - This tests that the method handles invalid date formats gracefully
        # The actual implementation may throw an error for malformed datetime strings
        with self.assertRaises((ValueError, Exception)):
            asyncio.run(self.telegramReportingService.setStartCommand(mock_task, "invalid-date-format"))

    def test_setDueCommand_relative_format(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        mock_task = MagicMock()
        mock_task.getDue.return_value = TimePoint.now()
        
        # Act
        asyncio.run(self.telegramReportingService.setDueCommand(mock_task, "+1d"))
        
        # Assert
        mock_task.setDue.assert_called_once()

    def test_setDueCommand_absolute_format(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setDueCommand(mock_task, "2024-01-01"))
        
        # Assert
        mock_task.setDue.assert_called_once()

    def test_setSeverityCommand(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setSeverityCommand(mock_task, "5.0"))
        
        # Assert
        mock_task.setSeverity.assert_called_once_with(5.0)

    def test_setTotalCostCommand(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setTotalCostCommand(mock_task, "2h"))
        
        # Assert
        mock_task.setTotalCost.assert_called_once()

    def test_setEffortInvestedCommand(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimeAmount
        mock_task = MagicMock()
        mock_task.getInvestedEffort.return_value = TimeAmount("1h")
        mock_task.getTotalCost.return_value = TimeAmount("3h")
        
        # Act
        asyncio.run(self.telegramReportingService.setEffortInvestedCommand(mock_task, "1h"))
        
        # Assert
        mock_task.setInvestedEffort.assert_called_once()
        mock_task.setTotalCost.assert_called_once()

    def test_setCalmCommand_true(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setCalmCommand(mock_task, "true"))
        
        # Assert
        mock_task.setCalm.assert_called_once_with(True)

    def test_setCalmCommand_false(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setCalmCommand(mock_task, "false"))
        
        # Assert
        mock_task.setCalm.assert_called_once_with(False)

    def test_processSetParam_valid_param(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.telegramReportingService.setDescriptionCommand = AsyncMock()
        
        # Act
        asyncio.run(self.telegramReportingService.processSetParam(mock_task, "description", "New Description"))
        
        # Assert
        self.telegramReportingService.setDescriptionCommand.assert_awaited_once_with(mock_task, "New Description")

    def test_processSetParam_invalid_param(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        
        # Act
        asyncio.run(self.telegramReportingService.processSetParam(mock_task, "invalid_param", "value"))
        
        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_nextCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.nextCommand("", False))

        # Assert
        self.task_list_manager.next_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_previousCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.previousCommand("", False))

        # Assert
        self.task_list_manager.prior_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_selectTaskCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.selectTaskCommand("task_1", False))

        # Assert
        self.task_list_manager.select_task.assert_called_once_with("task_1")
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_heuristicSelectionCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.heuristicSelectionCommand("test", False))

        # Assert
        self.task_list_manager.select_heuristic.assert_called_once_with("test")
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_algorithmSelectionCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.algorithmSelectionCommand("test", False))

        # Assert
        self.task_list_manager.select_algorithm.assert_called_once_with("test")
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_filterSelectionCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.filterSelectionCommand("test", False))

        # Assert
        self.task_list_manager.select_filter.assert_called_once_with("test")
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_doneCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand("", False))

        # Assert
        mock_task.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_setCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.setCommand("/set description test", False))

        # Assert
        self.telegramReportingService.processSetParam.assert_awaited_once_with(mock_task, "description", "test")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_newCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.taskProvider.createDefaultTask.return_value = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new test task", False))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("test task")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.task_list_manager.add_task.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_scheduleCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2h", False))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_task, "2h")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_workCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.workCommand("/work 1h", False))

        # Assert
        self.telegramReportingService.processSetParam.assert_awaited_once()
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.statisticsProvider.doWork.assert_called_once()
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_sendTaskList_not_interactive(self) -> None:
        # Arrange
        from src.Utils import TaskListContent
        mock_content = TaskListContent(
            algorithm_name="test_algorithm",
            algorithm_desc="test description",
            sort_heuristic="test_heuristic",
            tasks=[],
            total_tasks=0,
            current_page=1,
            total_pages=1,
            active_filters=[],
            interactive=True
        )
        self.task_list_manager.get_task_list_content.return_value = mock_content
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskList(False))

        # Assert
        self.task_list_manager.clear_selected_task.assert_called_once()
        self.task_list_manager.get_task_list_content.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_checkFilteredListChanges_empty_list(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 123
        filtered_list = []
        self.task_list_manager.filtered_task_list = filtered_list
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.messageBuilder.createOutboundMessage = MagicMock(return_value=MagicMock())

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_called_once()
        # When filtered list is empty, the method returns early, so these should NOT be called
        self.task_list_manager.reset_pagination.assert_not_called()
        self.messageBuilder.createOutboundMessage.assert_not_called()
        self.bot.sendMessage.assert_not_awaited()

    def test_projectCommand_valid_command(self) -> None:
        # Arrange
        from src.Interfaces.IProjectManager import ProjectCommands
        ProjectCommands.values = MagicMock(return_value=["help"])
        self.projectManager.process_command = MagicMock(return_value="Command executed")
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.projectCommand("/project help"))

        # Assert
        self.projectManager.process_command.assert_called_once_with("help", [])
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("Command executed")

    def test_importCommand_specific_format(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        self.telegramReportingService.listCommand = AsyncMock()
        mock_task_list = [MagicMock()]
        self.taskProvider.getTaskList.return_value = mock_task_list

        # Act
        asyncio.run(self.telegramReportingService.importCommand("/import json"))

        # Assert
        self.taskProvider.importTasks.assert_called_once_with("json")
        self.task_list_manager.update_taskList.assert_called_once_with(mock_task_list)
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()
        self.telegramReportingService.listCommand.assert_awaited_once()

    def test_scheduleCommand_no_params(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule"))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_task, "")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task)


if __name__ == '__main__':
    unittest.main()
