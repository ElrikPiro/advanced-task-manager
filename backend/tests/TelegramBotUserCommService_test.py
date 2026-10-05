import unittest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from src.MutationCoordinator import MutationCoordinator
from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.Interfaces.IFileBroker import IFileBroker
from src.Interfaces.IFileBroker import FileRegistry


class TestTelegramBotUserCommService(unittest.TestCase):

    def telegram_bot_mock(self):
        mock = AsyncMock()
        return mock

    def file_broker_mock(self):
        mock = Mock(spec=IFileBroker)
        return mock

    def build_service(self, telegram_bot_mock, file_broker_mock):
        return TelegramBotUserCommService(telegram_bot_mock, file_broker_mock, Mock())

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
        return TelegramBotUserCommService(telegram_bot_mock, file_broker_mock, Mock())

    def setUp(self):
        self.telegram_bot = self.telegram_bot_mock()
        self.file_broker = self.file_broker_mock()
        self.service = self.build_service(self.telegram_bot, self.file_broker)

    async def test_unauthorized_or_unconfigured_document_is_rejected_before_download_or_admission(self):
        for authorized_chat_id in ("999", None):
            with self.subTest(authorized_chat_id=authorized_chat_id):
                bot = AsyncMock()
                document_message = SimpleNamespace(
                    text=None,
                    document=SimpleNamespace(file_id="telegram-file-1"),
                    chat=SimpleNamespace(id=123),
                )
                bot.getUpdates.return_value = [
                    SimpleNamespace(update_id=7, message=document_message)
                ]
                coordinator = SimpleNamespace(run_job_async=AsyncMock())
                broker = SimpleNamespace(
                    writeFileContent=Mock(),
                    mutation_coordinator=coordinator,
                )
                service = TelegramBotUserCommService(
                    bot,
                    broker,
                    Mock(),
                    authorized_chat_id=authorized_chat_id,
                )

                result = await service._TelegramBotUserCommService__getMessageUpdates_legacy()

                self.assertIsNone(result)
                self.assertEqual(service.offset, 8)
                bot.get_file.assert_not_awaited()
                broker.writeFileContent.assert_not_called()
                coordinator.run_job_async.assert_not_awaited()

    async def test_authorized_document_is_downloaded_and_saved_in_shared_queue(self):
        bot = AsyncMock()
        document_message = SimpleNamespace(
            text=None,
            document=SimpleNamespace(file_id="telegram-file-1"),
            chat=SimpleNamespace(id=123),
        )
        bot.getUpdates.return_value = [SimpleNamespace(update_id=7, message=document_message)]
        telegram_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b'{"tasks": []}')))
        bot.get_file.return_value = telegram_file
        coordinator = MutationCoordinator()
        broker = SimpleNamespace(
            writeFileContent=Mock(),
            mutation_coordinator=coordinator,
        )
        service = TelegramBotUserCommService(
            bot,
            broker,
            Mock(),
            authorized_chat_id=123,
        )
        try:
            result = await service._TelegramBotUserCommService__getMessageUpdates_legacy()

            self.assertEqual(result, (123, "/import json"))
            bot.get_file.assert_awaited_once_with("telegram-file-1")
            telegram_file.download_as_bytearray.assert_awaited_once_with()
            broker.writeFileContent.assert_called_once_with(
                FileRegistry.LAST_RECEIVED_FILE,
                '{"tasks": []}',
            )
        finally:
            coordinator.close(wait=True)


if __name__ == '__main__':
    unittest.main()
