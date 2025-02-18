import unittest
import os
import json
from unittest.mock import patch, mock_open
from backend.src.FileBroker import FileBroker
from backend.src.Interfaces.IFileBroker import FileRegistry, VaultRegistry

class TestFileBroker(unittest.TestCase):

    def setUp(self):
        self.jsonPath = "/fake/json/path"
        self.appdata = "/fake/appdata/path"
        self.vaultPath = "/fake/vault/path"
        self.fileBroker = FileBroker(self.jsonPath, self.appdata, self.vaultPath)

    def test_readFileContent(self): #unwatched test
        with patch("builtins.open", mock_open(read_data="data")) as mock_file:
            self.assertEqual(self.fileBroker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON), "data")
            mock_file.assert_called_once_with(os.path.join(self.jsonPath, "tasks.json"), "r")

if __name__ == "__main__":
    unittest.main()
