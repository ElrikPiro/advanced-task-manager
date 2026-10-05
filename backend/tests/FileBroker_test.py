import unittest
import os
import json
import tempfile
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

    def test_readFileContent_WhenFileIsNotFound_ThenReturnDefaultWithoutCreating(self):
        with patch("builtins.open", side_effect=FileNotFoundError) as mock_file:
            readcontent = self.fileBroker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(readcontent, '{"tasks": []}')
        self.assertEqual(mock_file.call_count, 1)

    def test_readFileContentJson_WhenFileIsFound_ThenReturnFileContent(self):
        with patch("builtins.open", mock_open(read_data='{"key": "value"}')) as mock_file:
            readcontent = self.fileBroker.readFileContentJson(
                FileRegistry.STANDALONE_TASKS_JSON
            )
            self.assertEqual(readcontent, {"key": "value"})
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "r", errors="ignore")

    def test_readFileContentJson_WhenFileIsNotFound_ThenReturnDefaultWithoutCreating(self):
        with patch("builtins.open", side_effect=FileNotFoundError) as mock_file:
            readcontent = self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(readcontent, {"tasks": []})
        self.assertEqual(mock_file.call_count, 1)

    def test_readStatisticsFileContentJson_WhenFileIsMissing_ThenReturnSafeDefaultWithoutCreating(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = self.fileBroker.readStatisticsFileContentJson()
        self.assertEqual(result, {"log": []})

    def test_initializeFileContent_createsDefaultExplicitlyAndIsIdempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, os.path.join(directory, "app"), os.path.join(directory, "vault"))
            broker.initializeFileContent(FileRegistry.OBSIDIAN_TASKS_JSON)
            path = os.path.join(directory, "app", "obsidian", "tareas.json")
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), '{"tasks": []}')

            with open(path, "w", encoding="utf-8") as file:
                file.write('{"tasks": [{"description": "keep"}]}')
            broker.initializeFileContent(FileRegistry.OBSIDIAN_TASKS_JSON)
            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), '{"tasks": [{"description": "keep"}]}')

    def test_repeatedMissingReadsLeaveFilesystemUnchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path = os.path.join(directory, "json")
            appdata = os.path.join(directory, "appdata")
            vault_path = os.path.join(directory, "vault")
            broker = FileBroker(json_path, appdata, vault_path)
            before = sorted(
                os.path.join(root, name)
                for root, _, names in os.walk(directory)
                for name in names
            )

            for _ in range(2):
                self.assertEqual(broker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON), '{"tasks": []}')
                self.assertEqual(broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON), {"tasks": []})
                self.assertEqual(broker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON), {"tasks": []})
                self.assertEqual(broker.readFileContentJson(FileRegistry.LAST_RECEIVED_FILE), {"tasks": []})
                self.assertEqual(broker.readStatisticsFileContentJson(), {"log": []})
                self.assertEqual(broker.getVaultFiles(VaultRegistry.OBSIDIAN), [])
                with self.assertRaises(FileNotFoundError):
                    broker.getVaultFileLines(VaultRegistry.OBSIDIAN, "absent.md")

            after = sorted(
                os.path.join(root, name)
                for root, _, names in os.walk(directory)
                for name in names
            )
            self.assertEqual(after, before)
            self.assertFalse(os.path.exists(json_path))
            self.assertFalse(os.path.exists(appdata))
            self.assertFalse(os.path.exists(vault_path))

    def test_invalidJsonIsRaisedAndNeverReplaced(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            invalid_content = "{invalid-json"
            with open(path, "w", encoding="utf-8") as file:
                file.write(invalid_content)
            with open(path, "rb") as file:
                before = file.read()

            for _ in range(2):
                with self.assertRaises(json.JSONDecodeError):
                    broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)

            with open(path, "rb") as file:
                self.assertEqual(file.read(), before)

    @patch("os.walk")
    @patch("os.path.getmtime")
    def test_getVaultFiles_WhenFilesExist_ThenReturnFilePathsAndModificationTimes(self, mock_getmtime, mock_walk):
        fakePath = self.vaultPath
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
