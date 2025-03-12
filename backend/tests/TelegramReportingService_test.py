import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from src.TelegramReportingService import TelegramReportingService
import asyncio


class TestTelegramReportingService(unittest.TestCase):

    def setUp(self):
        self.bot = MagicMock()
        self.bot.sendMessage = AsyncMock()
        self.taskProvider = MagicMock()
        self.scheduling = MagicMock()
        self.statisticsProvider = MagicMock()
        self.task_list_manager = MagicMock()
        self.categories = [{"prefix": "@test"}]
        self.projectManager = MagicMock()

        self.telegramReportingService = TelegramReportingService(
            bot=self.bot,
            taskProvider=self.taskProvider,
            scheduling=self.scheduling,
            statiticsProvider=self.statisticsProvider,
            task_list_manager=self.task_list_manager,
            categories=self.categories,
            projectManager=self.projectManager,
            chatId=123456789
        )

    def test_projectCommand_no_command_provided(self):
        # Arrange
        messageText = "/project"

        # Act
        asyncio.run(self.telegramReportingService.projectCommand(messageText))

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="No project command provided"
        )

    def test_projectCommand_invalid_command(self):
        # Arrange
        messageText = "/project invalid_command"

        # Act
        asyncio.run(self.telegramReportingService.projectCommand(messageText))

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="Invalid project command"
        )

    def test_projectCommand_valid_command(self):
        # Arrange
        messageText = "/project list"
        self.projectManager.process_command.return_value = "Project list response"

        # Act
        asyncio.run(self.telegramReportingService.projectCommand(messageText))

        # Assert
        self.projectManager.process_command.assert_called_once_with("list", [])
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="Project list response"
        )

    def test_projectCommand_with_parameters(self):
        # Arrange
        messageText = "/project cat test_project"
        self.projectManager.process_command.return_value = "Project created"

        # Act
        asyncio.run(self.telegramReportingService.projectCommand(messageText))

        # Assert
        self.projectManager.process_command.assert_called_once_with("cat", ["test_project"])
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="Project created"
        )

    def test_processMessage_project_command(self):
        # Arrange
        messageText = "/project list"
        self.projectManager.process_command.return_value = "Project list response"

        # Act
        asyncio.run(self.telegramReportingService.processMessage(messageText))

        # Assert
        self.projectManager.process_command.assert_called_once_with("list", [])

    def test_processMessage_multiple_commands(self):
        # Arrange
        messageText = "/list\n/project list"
        self.projectManager.process_command.return_value = "Project list response"

        # Act
        asyncio.run(self.telegramReportingService.processMessage(messageText))

        # Assert
        self.projectManager.process_command.assert_called_once_with("list", [])
        self.task_list_manager.render_task_list_str.assert_called_once()

    def test_processMessage_unknown_command(self):
        # Arrange
        messageText = "/unknown_command"

        # Act
        asyncio.run(self.telegramReportingService.processMessage(messageText))

        # Assert
        self.bot.sendMessage.called_once_with(
            chat_id=123456789,
            text=self.telegramReportingService.helpCommand.__doc__
        )

    def test_checkFilteredListChanges_no_changes(self):
        # Arrange
        self.telegramReportingService.chatId = 123456789
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=False)

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.bot.sendMessage.assert_not_called()

    def test_checkFilteredListChanges_with_empty_list(self):
        # Arrange
        self.telegramReportingService.chatId = 123456789
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.task_list_manager.filtered_task_list = []
        self.task_list_manager.reset_pagination = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="Task /list updated"
        )
        self.task_list_manager.reset_pagination.assert_called_once()

    def test_checkFilteredListChanges_with_tasks(self):
        # Arrange
        self.telegramReportingService.chatId = 123456789
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        mockTask = MagicMock()
        mockTask.getDescription.return_value = "Test Task"
        self.task_list_manager.filtered_task_list = [mockTask]
        self.task_list_manager.reset_pagination = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="Task /list updated\n\n/task_1: Test Task"
        )
        self.task_list_manager.reset_pagination.assert_called_once()

    def test_checkFilteredListChanges_with_zero_chatId(self):
        # Arrange
        self.telegramReportingService.chatId = 0
        self.telegramReportingService.hasFilteredListChanged = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_not_called()
        self.bot.sendMessage.assert_not_called()

    def test_doneCommand_with_selected_task(self):
        # Arrange
        mockTask = MagicMock()
        mockTask.setStatus = MagicMock()
        self.task_list_manager.selected_task = mockTask
        self.taskProvider.saveTask = MagicMock()
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand())

        # Assert
        mockTask.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskList.assert_called_once()

    def test_doneCommand_without_selected_task(self):
        # Arrange
        self.task_list_manager.selected_task = None

        # Act
        asyncio.run(self.telegramReportingService.doneCommand())

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="no task selected."
        )

    def test_doneCommand_no_expectAnswer(self):
        # Arrange
        mockTask = MagicMock()
        mockTask.setStatus = MagicMock()
        self.task_list_manager.selected_task = mockTask
        self.taskProvider.saveTask = MagicMock()
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand(expectAnswer=False))

        # Assert
        mockTask.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskList.assert_not_called()

    @patch.object(TelegramReportingService, 'processSetParam')
    def test_setCommand_with_selected_task(self, mock_processSetParam):
        # Arrange
        mockTask = MagicMock()
        self.task_list_manager.selected_task = mockTask
        self.taskProvider.saveTask = MagicMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        messageText = "/set description New Task Description"
        mock_processSetParam.return_value = None

        # Act
        asyncio.run(self.telegramReportingService.setCommand(messageText))

        # Assert
        mock_processSetParam.assert_called_once_with(mockTask, "description", "New Task Description")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskInformation.assert_called_once_with(mockTask)

    @patch.object(TelegramReportingService, 'processSetParam')
    def test_setCommand_with_multiple_params(self, mock_processSetParam):
        # Arrange
        mockTask = MagicMock()
        self.task_list_manager.selected_task = mockTask
        self.taskProvider.saveTask = MagicMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        messageText = "/set context @test Project"
        mock_processSetParam.return_value = None

        # Act
        asyncio.run(self.telegramReportingService.setCommand(messageText))

        # Assert
        mock_processSetParam.assert_called_once_with(mockTask, "context", "@test Project")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskInformation.assert_called_once_with(mockTask)

    def test_setCommand_insufficient_params(self):
        # Arrange
        mockTask = MagicMock()
        self.task_list_manager.selected_task = mockTask
        self.taskProvider.saveTask = MagicMock()
        messageText = "/set"

        # Act & Assert
        with self.assertRaises(IndexError):
            asyncio.run(self.telegramReportingService.setCommand(messageText))

    def test_setCommand_no_selected_task(self):
        # Arrange
        self.task_list_manager.selected_task = None
        messageText = "/set description New Task Description"

        # Act
        asyncio.run(self.telegramReportingService.setCommand(messageText))

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="no task selected."
        )

    @patch.object(TelegramReportingService, 'processSetParam')
    def test_setCommand_no_expectAnswer(self, mock_processSetParam):
        # Arrange
        mockTask = MagicMock()
        self.task_list_manager.selected_task = mockTask
        self.taskProvider.saveTask = MagicMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        messageText = "/set severity 5"
        mock_processSetParam.return_value = None

        # Act
        asyncio.run(self.telegramReportingService.setCommand(messageText, expectAnswer=False))

        # Assert
        mock_processSetParam.assert_called_once_with(mockTask, "severity", "5")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskInformation.assert_not_called()

    def test_newCommand_with_description(self):
        # Arrange
        mockTask = MagicMock()
        self.taskProvider.createDefaultTask = MagicMock(return_value=mockTask)
        self.taskProvider.saveTask = MagicMock()
        self.task_list_manager.add_task = MagicMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        messageText = "/new Test task description"

        # Act
        asyncio.run(self.telegramReportingService.newCommand(messageText))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("Test task description")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.task_list_manager.add_task.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskInformation.assert_called_once_with(mockTask)

    def test_newCommand_with_extended_params(self):
        # Arrange
        mockTask = MagicMock()
        mockTask.setContext = MagicMock()
        mockTask.setTotalCost = MagicMock()
        self.taskProvider.createDefaultTask = MagicMock(return_value=mockTask)
        self.taskProvider.saveTask = MagicMock()
        self.task_list_manager.add_task = MagicMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        messageText = "/new Test task description;@test context;2p"

        # Act
        asyncio.run(self.telegramReportingService.newCommand(messageText))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("Test task description")
        mockTask.setContext.assert_called_once_with("@test context")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.task_list_manager.add_task.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskInformation.assert_called_once_with(mockTask)

    def test_newCommand_no_description(self):
        # Arrange
        messageText = "/new"

        # Act
        asyncio.run(self.telegramReportingService.newCommand(messageText))

        # Assert
        self.bot.sendMessage.assert_called_once_with(
            chat_id=123456789,
            text="no description provided."
        )

    def test_newCommand_no_expectAnswer(self):
        # Arrange
        mockTask = MagicMock()
        self.taskProvider.createDefaultTask = MagicMock(return_value=mockTask)
        self.taskProvider.saveTask = MagicMock()
        self.task_list_manager.add_task = MagicMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        messageText = "/new Test task description"

        # Act
        asyncio.run(self.telegramReportingService.newCommand(messageText, expectAnswer=False))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("Test task description")
        self.taskProvider.saveTask.assert_called_once_with(mockTask)
        self.task_list_manager.add_task.assert_called_once_with(mockTask)
        self.telegramReportingService.sendTaskInformation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
