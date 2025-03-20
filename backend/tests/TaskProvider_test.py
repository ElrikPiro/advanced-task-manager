import unittest
from unittest.mock import MagicMock
import json

from src.taskproviders.TaskProvider import TaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry


class TestTaskProvider(unittest.TestCase):
    def setUp(self):
        # Create mock dependencies
        self.mock_task_json_provider = MagicMock(spec=ITaskJsonProvider)
        self.mock_file_broker = MagicMock(spec=IFileBroker)

        # Sample task data for testing
        self.sample_tasks = {
            "tasks": [
                {
                    "description": "Task 1",
                    "context": "work",
                    "start": 1625097600000,
                    "due": 1625184000000,
                    "severity": 1.0,
                    "totalCost": 2.0,
                    "investedEffort": 0.5,
                    "status": " ",
                    "calm": "False",
                    "project": "Project1"
                },
                {
                    "description": "Task 2",
                    "context": "home",
                    "start": 1625097600000,
                    "due": 1625184000000,
                    "severity": 2.0,
                    "totalCost": 3.0,
                    "investedEffort": 1.0,
                    "status": "x",  # Completed task
                    "calm": "True",
                    "project": "Project2"
                },
                {
                    "description": "Task 3",
                    "context": "office",
                    "start": 1625097600000,
                    "due": 1625184000000,
                    "severity": 3.0,
                    "totalCost": 4.0,
                    "investedEffort": 1.5,
                    "status": " ",
                    "calm": "False",
                    "project": "Project1"
                }
            ]
        }

        # Configure mock behavior
        self.mock_task_json_provider.getJson.return_value = self.sample_tasks

        # Create the task provider with threading disabled
        self.task_provider = TaskProvider(
            self.mock_task_json_provider,
            self.mock_file_broker,
            disableThreading=True  # Disable threading for tests
        )

    def test_get_task_list(self):
        # Get task list
        task_list = self.task_provider.getTaskList()

        # Only non-completed tasks should be returned (2 of 3)
        self.assertEqual(len(task_list), 2)

        # Check first task properties
        self.assertEqual(task_list[0].getDescription(), "Task 1 @ Project1")
        self.assertEqual(task_list[0].getContext(), "work")
        self.assertEqual(task_list[0].getSeverity(), 1.0)
        self.assertEqual(task_list[0].getProject(), "Project1")
        # Completed tasks (status="x") should be filtered out
        descriptions = [task.getDescription() for task in task_list]
        self.assertIn("Task 1 @ Project1", descriptions)
        self.assertIn("Task 3 @ Project1", descriptions)
        self.assertNotIn("Task 2 @ Project1", descriptions)  # Task 2 is completed

    def test_create_task_from_dict(self):
        # Test task creation from dictionary
        test_task_dict = {
            "description": "Test Task",
            "context": "test",
            "start": 1625097600000,
            "due": 1625184000000,
            "severity": 2.5,
            "totalCost": 3.5,
            "investedEffort": 1.5,
            "status": " ",
            "calm": "True",
            "project": "TestProject"
        }

        task_model = self.task_provider.createTaskFromDict(test_task_dict, 0)

        self.assertEqual(task_model.getDescription(), "Test Task @ TestProject")
        self.assertEqual(task_model.getContext(), "test")
        self.assertEqual(task_model.getSeverity(), 2.5)
        self.assertEqual(task_model.getProject(), "TestProject")
        self.assertTrue(task_model.getCalm())

    def test_get_task_list_attribute(self):
        # Test existing attribute
        result = self.task_provider.getTaskListAttribute("tasks")
        self.assertEqual(result, self.sample_tasks["tasks"])
        # Test non-existing attribute
        result = self.task_provider.getTaskListAttribute("nonexistent")
        self.assertEqual(result, "")

    def test_save_task(self):
        # Get a task to modify and save
        task_list = self.task_provider.getTaskList()
        task = task_list[0]

        # Modify task
        task.setDescription("Updated Task 1")

        # Save the modified task
        self.task_provider.saveTask(task)

        # Verify saveJson was called
        self.mock_task_json_provider.saveJson.assert_called_once()

        # Check task was updated in the dictionary
        saved_task = next(t for t in self.task_provider.dict_task_list["tasks"] if t["description"] == "Updated Task 1")
        self.assertIsNotNone(saved_task)

    def test_create_default_task(self):
        # Create a default task
        task = self.task_provider.createDefaultTask("New Task")
        # Check task properties
        self.assertEqual(task.getDescription(), "New Task")
        self.assertEqual(task.getContext(), "workstation")
        self.assertEqual(task.getSeverity(), 1.0)
        self.assertEqual(task.getStatus(), " ")
        self.assertFalse(task.getCalm())

        # Ensure task was added to the task list
        self.assertIn(
            {"description": "New Task", "context": "workstation", "status": " ", "calm": "False"},
            [
                {k: t[k] for k in ["description", "context", "status", "calm"]}
                for t in self.task_provider.dict_task_list["tasks"]
            ]
        )

    def test_compare_tasks(self):
        # Create task lists for comparison
        task_list1 = self.task_provider.getTaskList()
        task_list2 = self.task_provider.getTaskList()

        # Lists should be equal
        self.assertTrue(self.task_provider.compare(task_list1, task_list2))

        # Create a different list
        task_list3 = task_list1[1:]
        self.assertFalse(self.task_provider.compare(task_list1, task_list3))

    def test_export_tasks_json(self):
        # Test JSON export
        exported_data = self.task_provider.exportTasks("json")

        # Should be a bytearray
        self.assertIsInstance(exported_data, bytearray)

        # Should contain valid JSON
        json_data = json.loads(exported_data.decode("utf-8"))
        self.assertIn("tasks", json_data)
        self.assertEqual(len(json_data["tasks"]), 3)

    def test_import_tasks_json(self):
        # Setup mock for file read
        test_import_data = {"tasks": [{"description": "Imported Task"}]}
        self.mock_file_broker.readFileContentJson.return_value = test_import_data

        # Perform import
        self.task_provider.importTasks("json")

        # Check if the imported data was saved
        self.mock_task_json_provider.saveJson.assert_called_once_with(test_import_data)
        self.mock_file_broker.readFileContentJson.assert_called_once_with(FileRegistry.LAST_RECEIVED_FILE)

    def test_callback_registration(self):
        # Create a mock callback
        mock_callback = MagicMock()

        # Register the callback
        self.task_provider.registerTaskListUpdatedCallback(mock_callback)

        # Check if callback was registered
        self.assertIn(mock_callback, self.task_provider.onTaskListUpdatedCallbacks)


if __name__ == "__main__":
    unittest.main()
