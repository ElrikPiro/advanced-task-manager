import unittest
from unittest.mock import MagicMock
from src.TaskJsonProvider import TaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry

class TaskJsonProviderTests(unittest.TestCase):
    def setUp(self):
        self.fileBroker = MagicMock(spec=IFileBroker)
        self.provider = TaskJsonProvider(self.fileBroker)

    def test_getJson(self):
        # Arrange
        expected_json = {"tasks": []}
        self.fileBroker.readFileContentJson.return_value = expected_json

        # Act
        result = self.provider.getJson()

        # Assert
        self.fileBroker.readFileContentJson.assert_called_once_with(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(result, expected_json)

    def test_saveJson(self):
        # Arrange
        json_data = {"tasks": []}

        # Act
        self.provider.saveJson(json_data)

        # Assert
        self.fileBroker.writeFileContentJson.assert_called_once_with(FileRegistry.STANDALONE_TASKS_JSON, json_data)

if __name__ == '__main__':
    unittest.main()
