import unittest
from unittest.mock import Mock, AsyncMock
from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.Interfaces.IFileBroker import IFileBroker
from unittest.mock import patch


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

    def test_preprocess_message_text_with_double_underscore(self):
        # Test with double underscore in the first word
        input_text = "command__name parameter1 parameter2"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/command name parameter1 parameter2"

    def test_preprocess_message_text_without_double_underscore(self):
        # Test with no double underscore
        input_text = "command parameter1 parameter2"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/command parameter1 parameter2"

    def test_preprocess_message_text_with_double_underscore_not_in_first_word(self):
        # Test with double underscore in a word that's not first
        input_text = "command param__eter1 parameter2"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/command param__eter1 parameter2"

    def test_preprocess_message_text_with_multiple_double_underscores_in_first_word(self):
        # Test with multiple double underscores in first word
        input_text = "comm__and__name parameter1 parameter2"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/comm and name parameter1 parameter2"

    def test_preprocess_message_text_single_word(self):
        # Test with just one word containing double underscore
        input_text = "command__name"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/command name"

    def test_preprocess_message_text_empty_string(self):
        # Test with empty string
        input_text = ""
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/"

    def test_preprocess_message_text_no_leading_slash(self):
        # Test with no leading slash in the input text
        input_text = "command"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/command"

    def test_preprocess_message_text_with_leading_slash(self):
        # Test with leading slash in the input text
        input_text = "/command"
        processed_text = self.service._TelegramBotUserCommService__preprocessMessageText(input_text)
        assert processed_text == "/command"


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

    async def test_getMessageUpdates_no_messages(self):
        # Test when no messages are available
        self.telegram_bot.getUpdates = AsyncMock(return_value=[])
        result = await self.service.getMessageUpdates()
        assert result is None
        self.telegram_bot.getUpdates.assert_called_once_with(
            limit=1, timeout=1, allowed_updates=['message'], offset=None)

    async def test_getMessageUpdates_with_text_message(self):
        # Test with a text message
        mock_update = AsyncMock()
        mock_update.update_id = 12345
        mock_update.message.text = "hello world"
        mock_update.message.chat.id = 67890
        mock_update.message.document = None

        self.telegram_bot.getUpdates = AsyncMock(return_value=[mock_update])

        result = await self.service.getMessageUpdates()
        assert result == (67890, "/hello world")
        assert self.service.offset == 12346  # update_id + 1

    async def test_getMessageUpdates_with_document(self):
        # Test with a document message
        mock_update = AsyncMock()
        mock_update.update_id = 12345
        mock_update.message.text = None
        mock_update.message.chat.id = 67890
        mock_update.message.document.file_id = "file123"

        mock_file = AsyncMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray("test content".encode()))

        self.telegram_bot.getUpdates = AsyncMock(return_value=[mock_update])
        self.telegram_bot.get_file = AsyncMock(return_value=mock_file)

        result = await self.service.getMessageUpdates()
        assert result == (67890, "/import json")
        assert self.service.offset == 12346  # update_id + 1
        self.file_broker.writeFileContent.assert_called_once()

    async def test_getMessageUpdates_with_other_content(self):
        # Test with a message that has neither text nor document
        mock_update = AsyncMock()
        mock_update.update_id = 12345
        mock_update.message.text = None
        mock_update.message.document = None

        self.telegram_bot.getUpdates = AsyncMock(return_value=[mock_update])

        result = await self.service.getMessageUpdates()
        assert result is None
        assert self.service.offset == 12346  # update_id + 1

    async def test_initialize(self):
        # Test initialize function
        await self.service.initialize()
        self.telegram_bot.initialize.assert_called_once()

    async def test_shutdown(self):
        # Test shutdown function
        await self.service.shutdown()
        self.telegram_bot.shutdown.assert_called_once()

    async def test_sendMessage(self):
        # Test sending a message
        chat_id = 12345
        text = "Test message"
        parse_mode = "HTML"

        await self.service.sendMessage(chat_id, text, parse_mode)
        self.telegram_bot.send_message.assert_called_once_with(chat_id, text, parse_mode=parse_mode)

    async def test_sendMessage_default_parse_mode(self):
        # Test sending a message with default parse_mode
        chat_id = 12345
        text = "Test message"

        await self.service.sendMessage(chat_id, text)
        self.telegram_bot.send_message.assert_called_once_with(chat_id, text, parse_mode=None)

    async def test_sendFile(self):
        # Test sending a file

        chat_id = 12345
        test_data = bytearray(b"Test file content")

        with patch('io.BufferedReader') as mock_buffered_reader:
            with patch('io.BytesIO') as mock_bytesio:
                mock_bytesio_instance = mock_bytesio.return_value
                mock_buffered_reader_instance = mock_buffered_reader.return_value
                mock_buffered_reader.return_value = mock_buffered_reader_instance

                await self.service.sendFile(chat_id, test_data)

                mock_bytesio.assert_called_once_with(test_data)
                mock_buffered_reader.assert_called_once_with(mock_bytesio_instance)
                self.telegram_bot.send_document.assert_called_once_with(
                    chat_id, mock_buffered_reader_instance, filename="export.txt"
                )


if __name__ == '__main__':
    unittest.main()
