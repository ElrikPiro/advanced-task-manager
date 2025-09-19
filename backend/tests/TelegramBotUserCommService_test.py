import unittest
from unittest.mock import Mock, AsyncMock
from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.Interfaces.IFileBroker import IFileBroker


class TestTelegramBotUserCommService(unittest.TestCase):

    def telegram_bot_mock(self):
        mock = AsyncMock()
        return mock

    def file_broker_mock(self):
        mock = Mock(spec=IFileBroker)
        return mock

    def build_service(self, telegram_bot_mock, file_broker_mock):
        return TelegramBotUserCommService(telegram_bot_mock, file_broker_mock)

    def setUp(self):
        self.telegram_bot = self.telegram_bot_mock()
        self.file_broker = self.file_broker_mock()
        self.service = self.build_service(self.telegram_bot, self.file_broker)


class TestTelegramBotUserCommServiceAsync(unittest.IsolatedAsyncioTestCase):

    def telegram_bot_mock(self):
        mock = AsyncMock()
        return mock

    def file_broker_mock(self):
        mock = Mock(spec=IFileBroker)
        return mock

    def build_service(self, telegram_bot_mock, file_broker_mock):
        return TelegramBotUserCommService(telegram_bot_mock, file_broker_mock)

    def setUp(self):
        self.telegram_bot = self.telegram_bot_mock()
        self.file_broker = self.file_broker_mock()
        self.service = self.build_service(self.telegram_bot, self.file_broker)


if __name__ == '__main__':
    unittest.main()
