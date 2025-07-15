import unittest
from unittest.mock import patch
from src.wrappers.ShellUserCommService import ShellUserCommService


class TestShellUserCommService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.chat_id = 12345
        self.service = ShellUserCommService(self.chat_id)

    async def test_initialize(self):
        with patch("builtins.print") as mock_print:
            await self.service.initialize()
            mock_print.assert_called_once_with("ShellUserBotService initialized")

    async def test_shutdown(self):
        with patch("builtins.print") as mock_print:
            await self.service.shutdown()
            mock_print.assert_called_once_with("ShellUserBotService shutdown")

    async def test_sendMessage(self):
        with patch("builtins.print") as mock_print:
            await self.service.sendMessage_legacy(self.chat_id, "Test message")
            mock_print.assert_called_once_with(f"[bot -> {self.chat_id}]: Test message")

    async def test_getMessageUpdates(self):
        with patch("builtins.input", return_value="test message"):
            result = await self.service.getMessageUpdates_legacy()
            assert result == (self.chat_id, "/test message")
            assert self.service.offset == 1

    async def test_sendFile(self):
        test_data = bytearray(b"Test file content")
        with patch("builtins.print") as mock_print:
            await self.service.sendFile_legacy(self.chat_id, test_data)
            mock_print.assert_any_call(f"[bot -> {self.chat_id}]: File sent")
            mock_print.assert_any_call(f"File content: {test_data[:128]}... ({len(test_data)} bytes)")


if __name__ == '__main__':
    unittest.main()
