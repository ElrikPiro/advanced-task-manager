import unittest
import os
from unittest.mock import patch, mock_open
from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry


class TestFileBroker(unittest.TestCase):

    def setUp(self):
        self.jsonPath = "/fake/json/path"
        self.appdata = "/fake/appdata/path"
        self.vaultPath = "/fake/vault/path"
        self.fileBroker = FileBroker(
            self.jsonPath,
            self.appdata,
            self.vaultPath
        )

    def test_readFileContent_WhenFileIsFound_ThenReturnFileContent(self):
        with patch("builtins.open", mock_open(read_data="data")) as mock_file:
            readcontent = self.fileBroker.readFileContent(
                FileRegistry.STANDALONE_TASKS_JSON
            )
            self.assertEqual(readcontent, "data")
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "r")

    def test_readFileContent_WhenFileIsNotFound_ThenCreateFileAndReturnDefaultContent(self):
        with patch.object(self.fileBroker, '_FileBroker__createFile', return_value=None):
            with patch("builtins.open", side_effect=FileNotFoundError):
                readcontent = self.fileBroker.readFileContent(
                    FileRegistry.STANDALONE_TASKS_JSON
                )
                self.assertEqual(readcontent, '{"tasks": [], "pomodoros_per_day": "2"}')

    def test_readFileContentJson_WhenFileIsFound_ThenReturnFileContent(self):
        with patch("builtins.open", mock_open(read_data='{"key": "value"}')) as mock_file:
            readcontent = self.fileBroker.readFileContentJson(
                FileRegistry.STANDALONE_TASKS_JSON
            )
            self.assertEqual(readcontent, {"key": "value"})
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "r")

    def test_readFileContentJson_WhenFileIsNotFound_ThenCreateFileAndReturnDefaultContent(self):
        with patch.object(self.fileBroker, '_FileBroker__createFile', return_value=None):
            with patch("builtins.open", side_effect=FileNotFoundError):
                readcontent = self.fileBroker.readFileContentJson(
                    FileRegistry.STANDALONE_TASKS_JSON
                )
                self.assertEqual(readcontent, {"tasks": [], "pomodoros_per_day": "2"})

    def test___createFile_WhenFileIsCreated_ThenReturnNone(self):
        with patch("builtins.open", mock_open()) as mock_file:
            self.fileBroker._FileBroker__createFile(FileRegistry.STANDALONE_TASKS_JSON)
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "w+")


if __name__ == "__main__":
    unittest.main()
