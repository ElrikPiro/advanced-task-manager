import unittest
from unittest.mock import MagicMock
from src.TaskProvider import TaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry
from src.TaskModel import TaskModel

class TaskProviderTests(unittest.TestCase):
    def setUp(self):
        self.taskJsonProvider = MagicMock(spec=ITaskJsonProvider)
        self.fileBroker = MagicMock(spec=IFileBroker)
        self.taskProvider = TaskProvider(self.taskJsonProvider, self.fileBroker)

    def test_get_task_list(self):
        # Mock the JSON data returned by the taskJsonProvider
        json_data = {
            "tasks": [
                {
                    "description": "Task 1",
                    "context": "Context 1",
                    "start": 1620000000000,
                    "due": 1625000000000,
                    "severity": 1.0,
                    "totalCost": 10.0,
                    "investedEffort": 5.0,
                    "status": "Open",
                    "calm": "True"
                },
                {
                    "description": "Task 2",
                    "context": "Context 2",
                    "start": 1621000000000,
                    "due": 1626000000000,
                    "severity": 2.0,
                    "totalCost": 8.0,
                    "investedEffort": 3.0,
                    "status": "In Progress",
                    "calm": "False"
                }
            ]
        }
        self.taskJsonProvider.getJson.return_value = json_data

        # Call the getTaskList method
        task_list = self.taskProvider.getTaskList()

        # Assert that the returned task list matches the expected task list
        self.assertEqual(len(task_list), 2)
        self.assertIsInstance(task_list[0], TaskModel)
        self.assertIsInstance(task_list[1], TaskModel)
        self.assertEqual(task_list[0].getDescription(), "Task 1")
        self.assertEqual(task_list[0].getContext(), "Context 1")
        self.assertEqual(task_list[0].getStart(), 1620000000000)
        self.assertEqual(task_list[0].getDue(), 1625000000000)
        self.assertEqual(task_list[0].getSeverity(), 1.0)
        self.assertEqual(task_list[0].getTotalCost(), 10.0)
        self.assertEqual(task_list[0].getInvestedEffort(), 5.0)
        self.assertEqual(task_list[0].getStatus(), "Open")
        self.assertTrue(task_list[0].getCalm())
        self.assertEqual(task_list[1].getDescription(), "Task 2")
        self.assertEqual(task_list[1].getContext(), "Context 2")
        self.assertEqual(task_list[1].getStart(), 1621000000000)
        self.assertEqual(task_list[1].getDue(), 1626000000000)
        self.assertEqual(task_list[1].getSeverity(), 2.0)
        self.assertEqual(task_list[1].getTotalCost(), 8.0)
        self.assertEqual(task_list[1].getInvestedEffort(), 3.0)
        self.assertEqual(task_list[1].getStatus(), "In Progress")
        self.assertFalse(task_list[1].getCalm())

    def test_save_task(self):
        # Mock the task to be saved
        task = MagicMock(spec=TaskModel)
        task.getDescription.return_value = "Task 1"
        task.getContext.return_value = "Context 1"
        task.getStart.return_value = 1620000000000
        task.getDue.return_value = 1625000000000
        task.getSeverity.return_value = 1.0
        task.getTotalCost.return_value = 10.0
        task.getInvestedEffort.return_value = 5.0
        task.getStatus.return_value = "Open"
        task.getCalm.return_value = True

        # Call the saveTask method
        self.taskProvider.saveTask(task)

        # Assert that the task was saved correctly
        self.taskJsonProvider.saveJson.assert_called_once()
        saved_json = self.taskJsonProvider.saveJson.call_args[0][0]
        self.assertEqual(len(saved_json["tasks"]), 1)
        self.assertEqual(saved_json["tasks"][0]["description"], "Task 1")
        self.assertEqual(saved_json["tasks"][0]["context"], "Context 1")
        self.assertEqual(saved_json["tasks"][0]["start"], 1620000000000)
        self.assertEqual(saved_json["tasks"][0]["due"], 1625000000000)
        self.assertEqual(saved_json["tasks"][0]["severity"], 1.0)
        self.assertEqual(saved_json["tasks"][0]["totalCost"], 10.0)
        self.assertEqual(saved_json["tasks"][0]["investedEffort"], 5.0)
        self.assertEqual(saved_json["tasks"][0]["status"], "Open")
        self.assertEqual(saved_json["tasks"][0]["calm"], "True")

    def test_create_default_task(self):
        # Call the createDefaultTask method
        task = self.taskProvider.createDefaultTask("Default Task")

        # Assert that the default task was created correctly
        self.assertIsInstance(task, TaskModel)
        self.assertEqual(task.getDescription(), "Default Task")
        self.assertEqual(task.getContext(), "workstation")
        self.assertEqual(task.getSeverity(), 1.0)
        self.assertEqual(task.getTotalCost(), 1.0)
        self.assertEqual(task.getInvestedEffort(), 0.0)
        self.assertEqual(task.getStatus(), " ")
        self.assertFalse(task.getCalm())

    def test_get_task_metadata(self):
        # Mock the task
        task = MagicMock(spec=TaskModel)
        task.getDescription.return_value = "Task 1"
        task.getContext.return_value = "Context 1"
        task.getStart.return_value = 1620000000000
        task.getDue.return_value = 1625000000000
        task.getSeverity.return_value = 1.0
        task.getTotalCost.return_value = 10.0
        task.getInvestedEffort.return_value = 5.0
        task.getStatus.return_value = "Open"
        task.getCalm.return_value = True

        # Call the getTaskMetadata method
        metadata = self.taskProvider.getTaskMetadata(task)

        # Assert that the metadata matches the expected content
        expected_metadata = "{'description': 'Task 1', 'context': 'Context 1', 'start': 1620000000000, 'due': 1625000000000, 'severity': 1.0, 'totalCost': 10.0, 'investedEffort': 5.0, 'status': 'Open', 'calm': 'True'}"
        self.assertEqual(metadata, expected_metadata)

if __name__ == '__main__':
    unittest.main()
