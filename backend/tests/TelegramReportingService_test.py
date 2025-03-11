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

    @patch.object(TelegramReportingService, 'projectCommand')
    @patch.object(TelegramReportingService, 'listCommand')
    def test_processMessage_project_command(self, mock_listCommand, mock_projectCommand):
        # Arrange
        messageText = "/project list"
        mock_projectCommand.return_value = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.processMessage(messageText))

        # Assert
        mock_projectCommand.assert_called_once_with(messageText, True)
        mock_listCommand.assert_not_called()

    @patch.object(TelegramReportingService, 'projectCommand')
    @patch.object(TelegramReportingService, 'listCommand')
    def test_processMessage_multiple_commands(self, mock_listCommand, mock_projectCommand):
        # Arrange
        messageText = "/list\n/project list"
        mock_projectCommand.return_value = AsyncMock()
        mock_listCommand.return_value = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.processMessage(messageText))

        # Assert
        mock_listCommand.assert_called_once_with("/list", False)
        mock_projectCommand.assert_called_once_with("/project list", True)

    @patch.object(TelegramReportingService, 'helpCommand')
    def test_processMessage_unknown_command(self, mock_helpCommand):
        # Arrange
        messageText = "/unknown_command"
        mock_helpCommand.return_value = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.processMessage(messageText))

        # Assert
        mock_helpCommand.assert_called_once_with("/unknown_command", True)


if __name__ == '__main__':
    unittest.main()