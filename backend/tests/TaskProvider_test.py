import unittest
from unittest.mock import MagicMock
import json
from copy import deepcopy

from src.taskproviders.TaskProvider import TaskProvider, TaskPrepareError
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError


class TestTaskProvider(unittest.TestCase):
    def setUp(self):
        # Create mock dependencies
        self.mock_task_json_provider = MagicMock(spec=ITaskJsonProvider)
        self.mock_file_broker = MagicMock(spec=IFileBroker)
        self.identity_path = "/configured/tasks.json"
        self.mock_file_broker.getFilePath.return_value = self.identity_path

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

        def update_json(updater):
            current = deepcopy(self.mock_task_json_provider.getJson())
            updated = updater(current)
            self.mock_task_json_provider.saveJson(deepcopy(updated))
            self.mock_task_json_provider.getJson.return_value = deepcopy(updated)
            return deepcopy(updated)

        self.mock_task_json_provider.updateJson.side_effect = update_json

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
        self.assertEqual(
            [task.getTaskUID() for task in task_list],
            [fallback_task_id("Task 1", self.identity_path, 0), fallback_task_id("Task 3", self.identity_path, 2)],
        )

    def test_get_task_list_can_include_completed_without_discovery(self):
        task_list = self.task_provider.getTaskList(include_completed=True)

        self.assertEqual(len(task_list), 3)
        self.assertEqual(task_list[1].getStatus(), "x")
        self.assertEqual(
            [task.getTaskUID() for task in task_list],
            [fallback_task_id(f"Task {index + 1}", self.identity_path, index) for index in range(3)],
        )
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
        self.assertEqual(task_model.getTaskUID(), fallback_task_id("Test Task", self.identity_path, 0))

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

        self.mock_task_json_provider.updateJson.assert_called_once()

        # Check task was updated in the dictionary
        saved_task = next(t for t in self.task_provider.dict_task_list["tasks"] if t["description"] == "Updated Task 1")
        self.assertIsNotNone(saved_task)

    def test_save_reasserts_explicit_unchanged_field_and_keeps_external_unrequested_edit(self):
        task = self.task_provider.getTaskList()[0]
        task._task_provider_forced_fields = {"description"}
        latest = deepcopy(self.sample_tasks)
        latest["tasks"][0]["id"] = task.getTaskUID()
        latest["tasks"][0]["description"] = "External title"
        latest["tasks"][0]["context"] = "external-context"
        self.mock_task_json_provider.getJson.return_value = latest

        self.task_provider.saveTask(task)

        saved = self.mock_task_json_provider.saveJson.call_args.args[0]["tasks"][0]
        self.assertEqual(saved["description"], "Task 1")
        self.assertEqual(saved["context"], "external-context")
        self.assertEqual(task.getRawDescription(), "Task 1")
        self.assertEqual(task.getContext(), "external-context")
        self.assertEqual(task._task_provider_forced_fields, set())

    def test_invalid_latest_model_record_fails_before_write_and_cache_publication(self):
        task = self.task_provider.getTaskList()[0]
        task.setDescription("Edited description")
        cache_before = deepcopy(self.task_provider.dict_task_list)
        latest = deepcopy(self.sample_tasks)
        latest["tasks"][0]["id"] = task.getTaskUID()
        latest["tasks"][0]["severity"] = "invalid"
        self.mock_task_json_provider.getJson.return_value = latest

        with self.assertRaises(TaskPrepareError) as raised:
            self.task_provider.saveTask(task)

        self.assertEqual(raised.exception.effects_state, "none")
        self.mock_task_json_provider.saveJson.assert_not_called()
        self.assertEqual(self.task_provider.dict_task_list, cache_before)

    def test_save_task_after_completed_record_preserves_full_json_and_unknown_fields(self):
        completed = self.sample_tasks["tasks"].pop(1)
        completed["source_note"] = "keep completed"
        self.sample_tasks["tasks"].insert(0, completed)
        self.sample_tasks["tasks"][1]["custom"] = {"owner": "test"}
        task = self.task_provider.getTaskList()[0]
        self.assertEqual(task.getTaskUID(), fallback_task_id("Task 1", self.identity_path, 1))
        task.setDescription("Updated Task 1")

        self.task_provider.saveTask(task)

        saved_json = self.mock_task_json_provider.saveJson.call_args.args[0]
        self.assertEqual(len(saved_json["tasks"]), 3)
        self.assertEqual(saved_json["tasks"][0]["status"], "x")
        self.assertEqual(saved_json["tasks"][0]["source_note"], "keep completed")
        self.assertEqual(saved_json["tasks"][1]["description"], "Updated Task 1")
        self.assertEqual(saved_json["tasks"][1]["custom"], {"owner": "test"})
        self.assertEqual(saved_json["tasks"][2]["description"], "Task 3")
        self.assertEqual(saved_json["tasks"][1]["id"], task.getTaskUID())

    def test_create_default_task(self):
        # Create a default task
        task = self.task_provider.createDefaultTask("New Task")
        # Check task properties
        self.assertEqual(task.getDescription(), "New Task")
        self.assertEqual(task.getContext(), "inbox")
        self.assertEqual(task.getSeverity(), 1.0)
        self.assertEqual(task.getStatus(), " ")
        self.assertFalse(task.getCalm())

        # A candidate remains private until its write is confirmed.
        self.assertEqual(len(self.task_provider.dict_task_list["tasks"]), 3)

    def test_create_default_task_then_save_appends_to_full_document(self):
        task = self.task_provider.createDefaultTask("New Task")
        self.task_provider.saveTask(task)

        saved_json = self.mock_task_json_provider.saveJson.call_args.args[0]
        self.assertEqual(len(saved_json["tasks"]), 4)
        self.assertEqual(saved_json["tasks"][:3], self.sample_tasks["tasks"])
        self.assertEqual(saved_json["tasks"][3]["description"], "New Task")
        self.assertEqual(saved_json["tasks"][3]["id"], task.getTaskUID())

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
        expected_ids = [fallback_task_id(f"Part {index}", self.identity_path, index + 3) for index in range(3)]
        self.assertEqual([task.getTaskUID() for task in tasks], expected_ids)

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
        self.assertEqual([record["id"] for record in storage["tasks"][3:]], expected_ids)

    def test_failed_save_keeps_candidate_until_caller_discards_reservation(self):
        task = self.task_provider.createDefaultTask("Failed part")
        self.mock_task_json_provider.saveJson.side_effect = OSError("disk full")
        with self.assertRaisesRegex(OSError, "disk full"):
            self.task_provider.saveTask(task)

        self.task_provider.discardPendingTaskReservations()
        self.mock_task_json_provider.saveJson.side_effect = None
        next_task = self.task_provider.createDefaultTask("Next part")
        self.assertEqual(next_task.getTaskUID(), fallback_task_id("Next part", self.identity_path, 3))

    def test_save_persists_identity_before_a_later_description_change(self):
        task = self.task_provider.getTaskList()[0]
        original_id = task.getTaskUID()
        task.setDescription("Updated before first save")

        self.task_provider.saveTask(task)
        saved = self.mock_task_json_provider.saveJson.call_args.args[0]["tasks"][0]

        self.assertEqual(saved["id"], original_id)
        self.assertEqual(task.getTaskUID(), original_id)

    def test_save_resolves_by_id_after_position_changes_and_preserves_completed_records(self):
        source = json.loads(json.dumps(self.sample_tasks))
        original_target = source["tasks"].pop(0)
        captured_id = fallback_task_id(original_target["description"], self.identity_path, 0)
        original_target["id"] = captured_id
        source["tasks"].append(original_target)
        self.mock_task_json_provider.getJson.return_value = source
        task = self.task_provider.createTaskFromDict(original_target, 0, captured_id, self.identity_path)
        task.setDescription("Moved and edited")

        self.task_provider.saveTask(task)

        saved = self.mock_task_json_provider.saveJson.call_args.args[0]
        self.assertEqual(saved["tasks"][0]["status"], "x")
        self.assertEqual(saved["tasks"][-1]["description"], "Moved and edited")
        self.assertEqual(saved["tasks"][-1]["id"], captured_id)

    def test_duplicate_task_ids_block_writes(self):
        duplicate = json.loads(json.dumps(self.sample_tasks))
        duplicate_id = fallback_task_id("Task 1", self.identity_path, 0)
        duplicate["tasks"][0]["id"] = duplicate_id
        duplicate["tasks"][2]["id"] = duplicate_id
        self.mock_task_json_provider.getJson.return_value = duplicate
        task = self.task_provider.createTaskFromDict(duplicate["tasks"][0], 0, duplicate_id, self.identity_path)

        with self.assertRaisesRegex(AmbiguousTaskIdentityError, "multiple stored tasks"):
            self.task_provider.saveTask(task)
        self.mock_task_json_provider.updateJson.assert_called_once()
        self.mock_task_json_provider.saveJson.assert_not_called()

    def test_invalid_declared_ids_are_rejected_without_rewriting_data(self):
        self.mock_task_json_provider.getJson.return_value = {
            "tasks": [{**self.sample_tasks["tasks"][0], "id": "  \t"}]
        }

        with self.assertRaisesRegex(InvalidTaskIdentityError, "non-empty string"):
            self.task_provider.getTaskList()

        self.mock_task_json_provider.saveJson.assert_not_called()

    def test_pending_new_task_identity_collision_blocks_save(self):
        task = self.task_provider.createDefaultTask("New task")
        source = json.loads(json.dumps(self.sample_tasks))
        collision = dict(source["tasks"][0])
        collision["id"] = task.getTaskUID()
        source["tasks"].append(collision)
        self.mock_task_json_provider.getJson.return_value = source

        with self.assertRaisesRegex(AmbiguousTaskIdentityError, "pending new task"):
            self.task_provider.saveTask(task)

        self.mock_task_json_provider.saveJson.assert_not_called()

    def test_new_task_identity_collision_blocks_reservation(self):
        source = json.loads(json.dumps(self.sample_tasks))
        source["tasks"][0]["id"] = fallback_task_id("New task", self.identity_path, len(source["tasks"]))
        self.mock_task_json_provider.getJson.return_value = source

        with self.assertRaisesRegex(AmbiguousTaskIdentityError, "conflicts with an existing task"):
            self.task_provider.createDefaultTask("New task")

    def test_save_preserves_raw_description_with_project_delimiter_and_spaces(self):
        task = self.task_provider.getTaskList()[0]
        task.setDescription("  Research @ annotation  ")

        self.task_provider.saveTask(task)

        saved_json = self.mock_task_json_provider.saveJson.call_args.args[0]
        self.assertEqual(saved_json["tasks"][0]["description"], "  Research @ annotation  ")

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
        self.mock_task_json_provider.updateJson.assert_called_once()
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
