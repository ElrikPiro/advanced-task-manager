import unittest
import os
from unittest.mock import patch, mock_open
from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry, VaultRegistry


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
            mock_file.assert_called_once_with(filePath, "r", errors="ignore")

    def test_readFileContent_WhenFileIsNotFound_ThenCreateFileAndReturnDefaultContent(self):
        with patch.object(self.fileBroker, '_FileBroker__createFile', return_value=None):
            with patch("builtins.open", side_effect=FileNotFoundError):
                readcontent = self.fileBroker.readFileContent(
                    FileRegistry.STANDALONE_TASKS_JSON
                )
                self.assertEqual(readcontent, '{"tasks": []}')

    def test_readFileContentJson_WhenFileIsFound_ThenReturnFileContent(self):
        with patch("builtins.open", mock_open(read_data='{"key": "value"}')) as mock_file:
            readcontent = self.fileBroker.readFileContentJson(
                FileRegistry.STANDALONE_TASKS_JSON
            )
            self.assertEqual(readcontent, {"key": "value"})
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "r", errors="ignore")

    def test_readFileContentJson_WhenFileIsNotFound_ThenCreateFileAndReturnDefaultContent(self):
        with patch.object(self.fileBroker, '_FileBroker__createFile', return_value=None):
            with patch("builtins.open", side_effect=FileNotFoundError):
                readcontent = self.fileBroker.readFileContentJson(
                    FileRegistry.STANDALONE_TASKS_JSON
                )
                self.assertEqual(readcontent, {"tasks": []})

    def test___createFile_WhenFileIsCreated_ThenReturnNone(self):
        with patch("builtins.open", mock_open()) as mock_file:
            self.fileBroker._FileBroker__createFile(FileRegistry.STANDALONE_TASKS_JSON)
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "w+")

    @patch("os.walk")
    @patch("os.path.getmtime")
    def test_getVaultFiles_WhenFilesExist_ThenReturnFilePathsAndModificationTimes(self, mock_getmtime, mock_walk):
        fakePath = os.path.join("fake", "vault", "path")
        mock_walk.return_value = [
            (fakePath, ("subdir",), ("file1.txt", "file2.txt")),
            (os.path.join(fakePath, "subdir"), (), ("file3.txt",))
        ]
        mock_getmtime.side_effect = [1000.0, 2000.0, 3000.0]

        expected_files = [
            (os.path.join("file1.txt"), 1000.0),
            (os.path.join("file2.txt"), 2000.0),
            (os.path.join("subdir", "file3.txt"), 3000.0)
        ]

        files = self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        self.assertEqual(files, expected_files)

    @patch("os.walk")
    def test_getVaultFiles_WhenNoFilesExist_ThenReturnEmptyList(self, mock_walk):
        mock_walk.return_value = []

        files = self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        self.assertEqual(files, [])

    @patch("builtins.open", new_callable=mock_open, read_data="line1\nline2\nline3\n")
    def test_getVaultFileLines_WhenFileExists_ThenReturnFileLines(self, mock_file):
        lines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, "testfile.md")
        self.assertEqual(lines, ["line1\n", "line2\n", "line3\n"])
        filePath = os.path.join(self.vaultPath, "testfile.md")
        mock_file.assert_called_once_with(filePath, "r", errors="ignore")

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_getVaultFileLines_WhenFileDoesNotExist_ThenRaiseFileNotFoundError(self, mock_file):
        with self.assertRaises(FileNotFoundError):
            self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, "nonexistentfile.md")
        filePath = os.path.join(self.vaultPath, "nonexistentfile.md")
        mock_file.assert_called_once_with(filePath, "r", errors="ignore")


if __name__ == "__main__":
    unittest.main()
