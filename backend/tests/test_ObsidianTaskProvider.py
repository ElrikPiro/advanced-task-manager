import unittest
from unittest.mock import MagicMock
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.ObsidianTaskModel import ObsidianTaskModel

class ObsidianTaskProviderTests(unittest.TestCase):
    def setUp(self):
        self.taskJsonProvider = MagicMock(spec=ITaskJsonProvider)
        self.taskProvider = ObsidianTaskProvider(self.taskJsonProvider)

    def test_get_task_list(self):
        # Mock the JSON data returned by the taskJsonProvider
        json_data = [
            {
                "taskText": "Task 1",
                "track": "Track 1",
                "starts": "2022-01-01",
                "due": "2022-01-10",
                "severity": "High",
                "total_cost": 10,
                "effort_invested": 5,
                "file": "file1.py",
                "line": 10,
                "status": "Open"
            },
            {
                "taskText": "Task 2",
                "track": "Track 2",
                "starts": "2022-01-05",
                "due": "2022-01-15",
                "severity": "Medium",
                "total_cost": 8,
                "effort_invested": 3,
                "file": "file2.py",
                "line": 20,
                "status": "In Progress"
            }
        ]
        self.taskJsonProvider.getJson.return_value = json_data

        # Call the getTaskList method
        task_list = self.taskProvider.getTaskList()

        # Assert that the returned task list matches the expected task list
        self.assertEqual(len(task_list), 2)
        self.assertIsInstance(task_list[0], ObsidianTaskModel)
        self.assertIsInstance(task_list[1], ObsidianTaskModel)
        self.assertEqual(task_list[0].getDescription(), "Task 1")
        self.assertEqual(task_list[0].getContext(), "Track 1")
        self.assertEqual(task_list[0].getStart(), "2022-01-01")
        self.assertEqual(task_list[0].getDue(), "2022-01-10")
        self.assertEqual(task_list[0].getSeverity(), "High")
        self.assertEqual(task_list[0].getTotalCost(), 10)
        self.assertEqual(task_list[0].getInvestedEffort(), 5)
        self.assertEqual(task_list[0].getFile(), "file1.py")
        self.assertEqual(task_list[0].getLine(), 10)
        self.assertEqual(task_list[0].getStatus(), "Open")
        self.assertEqual(task_list[1].getDescription(), "Task 2")
        self.assertEqual(task_list[1].getContext(), "Track 2")
        self.assertEqual(task_list[1].getStart(), "2022-01-05")
        self.assertEqual(task_list[1].getDue(), "2022-01-15")
        self.assertEqual(task_list[1].getSeverity(), "Medium")
        self.assertEqual(task_list[1].getTotalCost(), 8)
        self.assertEqual(task_list[1].getInvestedEffort(), 3)
        self.assertEqual(task_list[1].getFile(), "file2.py")
        self.assertEqual(task_list[1].getLine(), 20)
        self.assertEqual(task_list[1].getStatus(), "In Progress")

    def test_save_task(self):
        # Mock the task to be saved
        task = MagicMock(spec=ObsidianTaskModel)
        task.getDescription.return_value = "Task 1"
        task.getContext.return_value = "Track 1"
        task.getStart.return_value = "2022-01-01"
        task.getDue.return_value = "2022-01-10"
        task.getSeverity.return_value = "High"
        task.getTotalCost.return_value = 10
        task.getInvestedEffort.return_value = 5
        task.getFile.return_value = "file1.py"
        task.getLine.return_value = 10
        task.getStatus.return_value = "Open"

        # Call the saveTask method
        self.taskProvider.saveTask(task)

        # Assert that the task was saved correctly
        self.taskJsonProvider.saveJson.assert_called_once()
        saved_json = self.taskJsonProvider.saveJson.call_args[0][0]
        self.assertEqual(len(saved_json["tasks"]), 1)
        self.assertEqual(saved_json["tasks"][0]["description"], "Task 1")
        self.assertEqual(saved_json["tasks"][0]["context"], "Track 1")
        self.assertEqual(saved_json["tasks"][0]["start"], "2022-01-01")
        self.assertEqual(saved_json["tasks"][0]["due"], "2022-01-10")
        self.assertEqual(saved_json["tasks"][0]["severity"], "High")
        self.assertEqual(saved_json["tasks"][0]["totalCost"], 10)
        self.assertEqual(saved_json["tasks"][0]["investedEffort"], 5)
        self.assertEqual(saved_json["tasks"][0]["file"], "file1.py")
        self.assertEqual(saved_json["tasks"][0]["line"], 10)
        self.assertEqual(saved_json["tasks"][0]["status"], "Open")

    def test_create_default_task(self):
        # Call the createDefaultTask method
        task = self.taskProvider.createDefaultTask("Default Task")

        # Assert that the default task was created correctly
        self.assertIsInstance(task, ObsidianTaskModel)
        self.assertEqual(task.getDescription(), "Default Task")
        self.assertEqual(task.getContext(), "workstation")
        self.assertEqual(task.getSeverity(), 1.0)
        self.assertEqual(task.getTotalCost(), 1.0)
        self.assertEqual(task.getInvestedEffort(), 0.0)
        self.assertEqual(task.getStatus(), " ")
        self.assertEqual(task.getCalm(), False)

    def test_get_task_metadata(self):
        # Mock the task
        task = MagicMock(spec=ObsidianTaskModel)
        task.getFile.return_value = "file1.py"
        task.getLine.return_value = 10

        # Mock the file content
        file_content = [
            "Line 1\n",
            "Line 2\n",
            "Line 3\n",
            "Line 4\n",
            "Line 5\n"
        ]
        self.taskProvider.fileBroker.getVaultFileLines.return_value = file_content

        # Call the getTaskMetadata method
        metadata = self.taskProvider.getTaskMetadata(task)

        # Assert that the metadata matches the expected content
        expected_metadata = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
        self.assertEqual(metadata, expected_metadata)

if __name__ == '__main__':
    unittest.main()
