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
        self.assertEqual([task.getTaskUID() for task in task_list], ["0", "2"])

    def test_get_task_list_can_include_completed_without_discovery(self):
        task_list = self.task_provider.getTaskList(include_completed=True)

        self.assertEqual(len(task_list), 3)
        self.assertEqual(task_list[1].getStatus(), "x")
        self.assertEqual([task.getTaskUID() for task in task_list], ["0", "1", "2"])
        self.mock_task_json_provider.discover.assert_not_called()

    def test_discover_tasks_uses_explicit_provider_hook(self):
        result = self.task_provider.discoverTasks()

        self.mock_task_json_provider.discover.assert_called_once_with()
        self.assertEqual(len(result), 2)

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
        self.assertEqual(result, [])

    def test_get_task_list_attribute_propagates_read_errors_and_invalid_shapes(self):
        self.mock_task_json_provider.getJson.side_effect = OSError("storage unavailable")
        with self.assertRaisesRegex(OSError, "storage unavailable"):
            self.task_provider.getTaskListAttribute("projects")

        self.mock_task_json_provider.getJson.side_effect = None
        self.mock_task_json_provider.getJson.return_value = {"projects": {"unexpected": "object"}}
        with self.assertRaisesRegex(TypeError, "projects.*must be a list"):
            self.task_provider.getTaskListAttribute("projects")

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

    def test_save_task_after_completed_record_preserves_full_json_and_unknown_fields(self):
        completed = self.sample_tasks["tasks"].pop(1)
        completed["source_note"] = "keep completed"
        self.sample_tasks["tasks"].insert(0, completed)
        self.sample_tasks["tasks"][1]["custom"] = {"owner": "test"}
        task = self.task_provider.getTaskList()[0]
        self.assertEqual(task.getTaskUID(), "1")
        task.setDescription("Updated Task 1")

        self.task_provider.saveTask(task)

        saved_json = self.mock_task_json_provider.saveJson.call_args.args[0]
        self.assertEqual(len(saved_json["tasks"]), 3)
        self.assertEqual(saved_json["tasks"][0]["status"], "x")
        self.assertEqual(saved_json["tasks"][0]["source_note"], "keep completed")
        self.assertEqual(saved_json["tasks"][1]["description"], "Updated Task 1")
        self.assertEqual(saved_json["tasks"][1]["custom"], {"owner": "test"})
        self.assertEqual(saved_json["tasks"][2]["description"], "Task 3")

    def test_create_default_task(self):
        # Create a default task
        task = self.task_provider.createDefaultTask("New Task")
        # Check task properties
        self.assertEqual(task.getDescription(), "New Task")
        self.assertEqual(task.getContext(), "inbox")
        self.assertEqual(task.getSeverity(), 1.0)
        self.assertEqual(task.getStatus(), " ")
        self.assertFalse(task.getCalm())

        # Ensure task was added to the task list
        self.assertIn(
            {"description": "New Task", "context": "inbox", "status": " ", "calm": "False"},
            [
                {k: t[k] for k in ["description", "context", "status", "calm"]}
                for t in self.task_provider.dict_task_list["tasks"]
            ]
        )

    def test_create_default_task_then_save_appends_to_full_document(self):
        task = self.task_provider.createDefaultTask("New Task")
        self.task_provider.saveTask(task)

        saved_json = self.mock_task_json_provider.saveJson.call_args.args[0]
        self.assertEqual(len(saved_json["tasks"]), 4)
        self.assertEqual(saved_json["tasks"][:3], self.sample_tasks["tasks"])
        self.assertEqual(saved_json["tasks"][3]["description"], "New Task")

    def test_multiple_deferred_default_tasks_reserve_distinct_physical_positions(self):
        storage = json.loads(json.dumps(self.sample_tasks))

        def read_storage():
            return json.loads(json.dumps(storage))

        def save_storage(document):
            storage.clear()
            storage.update(json.loads(json.dumps(document)))

        self.mock_task_json_provider.getJson.side_effect = read_storage
        self.mock_task_json_provider.saveJson.side_effect = save_storage
        storage["tasks"][1]["custom"] = "keep completed"
        storage["tasks"][2]["custom"] = "keep original"

        tasks = [self.task_provider.createDefaultTask(f"Part {index}") for index in range(3)]
        self.assertEqual([task.getTaskUID() for task in tasks], ["3", "4", "5"])

        for task in tasks:
            self.task_provider.saveTask(task)

        self.assertEqual(len(storage["tasks"]), 6)
        self.assertEqual(storage["tasks"][1]["status"], "x")
        self.assertEqual(storage["tasks"][1]["custom"], "keep completed")
        self.assertEqual(storage["tasks"][2]["description"], "Task 3")
        self.assertEqual(storage["tasks"][2]["custom"], "keep original")
        self.assertEqual(
            [record["description"] for record in storage["tasks"][3:]],
            ["Part 0", "Part 1", "Part 2"],
        )

    def test_failed_save_releases_new_task_reservation_without_position_gap(self):
        task = self.task_provider.createDefaultTask("Failed part")
        self.mock_task_json_provider.saveJson.side_effect = OSError("disk full")
        with self.assertRaisesRegex(OSError, "disk full"):
            self.task_provider.saveTask(task)

        self.mock_task_json_provider.saveJson.side_effect = None
        next_task = self.task_provider.createDefaultTask("Next part")
        self.assertEqual(next_task.getTaskUID(), "3")

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
