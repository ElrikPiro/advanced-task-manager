import unittest
from unittest.mock import patch, mock_open, MagicMock
from src.FileBroker import FileBroker, FileRegistry, VaultRegistry

class TestFileBroker(unittest.TestCase):

    @patch("builtins.open", new_callable=mock_open, read_data='{"tasks": [], "pomodoros_per_day": "2"}')
    def setUp(self, mock_file):
        self.fileBroker = FileBroker("/mock/jsonPath", "/mock/appdata", "/mock/vaultPath")

    @patch("builtins.open", new_callable=mock_open, read_data='{"tasks": [], "pomodoros_per_day": "2"}')
    def test_readFileContent(self, mock_file):
        content = self.fileBroker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(content, '{"tasks": [], "pomodoros_per_day": "2"}')

    @patch("builtins.open", new_callable=mock_open, read_data='{"tasks": [], "pomodoros_per_day": "2"}')
    def test_readFileContentJson(self, mock_file):
        content = self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(content, {"tasks": [], "pomodoros_per_day": "2"})

    @patch("builtins.open", new_callable=mock_open)
    def test_writeFileContent(self, mock_file):
        self.fileBroker.writeFileContent(FileRegistry.STANDALONE_TASKS_JSON, '{"tasks": [], "pomodoros_per_day": "2"}')
        mock_file.assert_called_once_with("/mock/jsonPath/tasks.json", "w+")
        mock_file().write.assert_called_once_with('{"tasks": [], "pomodoros_per_day": "2"}')

    @patch("builtins.open", new_callable=mock_open)
    def test_writeFileContentJson(self, mock_file):
        self.fileBroker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, {"tasks": [], "pomodoros_per_day": "2"})
        mock_file.assert_called_once_with("/mock/jsonPath/tasks.json", "w+")
        mock_file().write.assert_called_once_with('{\n    "tasks": [],\n    "pomodoros_per_day": "2"\n}')

    @patch("builtins.open", new_callable=mock_open, read_data="line1\nline2\nline3")
    def test_getVaultFileLines(self, mock_file):
        lines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, "test.md")
        self.assertEqual(lines, ["line1\n", "line2\n", "line3"])

    @patch("builtins.open", new_callable=mock_open)
    def test_writeVaultFileLines(self, mock_file):
        self.fileBroker.writeVaultFileLines(VaultRegistry.OBSIDIAN, "test.md", ["line1\n", "line2\n", "line3"])
        mock_file.assert_called_once_with("/mock/vaultPath/test.md", "w")
        mock_file().writelines.assert_called_once_with(["line1\n", "line2\n", "line3"])

if __name__ == "__main__":
    unittest.main()
