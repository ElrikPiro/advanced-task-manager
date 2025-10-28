import unittest
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


if __name__ == '__main__':
    unittest.main()
