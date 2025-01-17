import unittest
from unittest.mock import MagicMock
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.taskmodels.ObsidianTaskModel import ObsidianTaskModel

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

if __name__ == '__main__':
    unittest.main()