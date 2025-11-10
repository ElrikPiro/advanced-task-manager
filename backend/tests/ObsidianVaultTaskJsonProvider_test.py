import unittest
from unittest.mock import MagicMock
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, VaultRegistry
from src.wrappers.TimeManagement import TimePoint
from src.Utils import TaskDiscoveryPolicies


class TestObsidianVaultTaskJsonProvider(unittest.TestCase):

    def setUp(self):
        self.mock_file_broker = MagicMock(spec=IFileBroker)
        self.policies = TaskDiscoveryPolicies(
            context_missing_policy="0",
            date_missing_policy="0",
            default_context="inbox",
            categories_prefixes=["work"]
        )
        self.provider = ObsidianVaultTaskJsonProvider(self.mock_file_broker, self.policies)

    def test_empty_vault_returns_empty_dict(self):
        self.mock_file_broker.getVaultFiles.return_value = []
        result = self.provider.getJson()
        self.assertEqual(result, {})
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)

    def test_no_changes_returns_cached_json(self):
        # First call to set up cache
        self.mock_file_broker.getVaultFiles.return_value = [("test.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = ["---", "---"]
        self.provider.getJson()

        # Second call with same mtime should use cache
        self.mock_file_broker.getVaultFiles.return_value = [("test.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.reset_mock()

        self.provider.getJson()
        self.mock_file_broker.getVaultFileLines.assert_not_called()

    def test_process_task_file_with_project_header(self):
        self.mock_file_broker.getVaultFiles.return_value = [("project.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "project: open",
            "---",
            "# Project Title"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["projects"]), 1)
        self.assertEqual(result["projects"][0]["name"], "project")
        self.assertEqual(result["projects"][0]["status"], "open")
        self.assertEqual(result["projects"][0]["path"], "project.md")

        # Should create a default "Define next action" task for open projects
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Define next action")

    def test_process_task_with_metadata(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Complete report [track::work] [start::2023-12-31] [due::2023-12-31] [severity::3] [remaining_cost::2] [invested::1]"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        task = result["tasks"][0]
        self.assertEqual(task["taskText"], "Complete report")
        self.assertEqual(task["due"], str(TimePoint.from_string("2023-12-31").as_int()))
        self.assertEqual(task["severity"], "3.0")
        self.assertEqual(task["remaining_cost"], "2")
        self.assertEqual(task["invested"], "1")
        self.assertEqual(task["total_cost"], "1.0")

    def test_invalid_task_is_skipped(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Invalid task without track tag"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 0)

    def test_file_header_values_applied_to_tasks(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "severity: 5",
            "starts: 2023-01-01",
            "---",
            "- [ ] Task with header values [track::work]"
        ]

        result = self.provider.getJson()
        task = result["tasks"][0]
        self.assertEqual(task["severity"], "5.0")
        self.assertEqual(task["starts"], str(TimePoint.from_string("2023-01-01").as_int()))

    def test_update_existing_task(self):
        # First call to add a task
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task 1 [track::work]"
        ]
        self.provider.getJson()

        # Second call to update the same task
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 200.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task 1 updated [track::work]"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Task 1 updated")

    def test_error_handling_during_file_processing(self):
        self.mock_file_broker.getVaultFiles.return_value = [("valid.md", 100.0), ("invalid.md", 200.0)]

        def mock_get_file_lines(registry, path):
            if path == "valid.md":
                return ["- [ ] Valid task [track::work]"]
            else:
                raise Exception("Test error")

        self.mock_file_broker.getVaultFileLines.side_effect = mock_get_file_lines

        # Should process the valid file and catch the exception for the invalid file
        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)

    def test_saveJson_does_nothing(self):
        # saveJson should be a no-op
        self.provider.saveJson({"tasks": []})
        # No assertions needed as the method doesn't do anything

    def test_update_or_append_task_functionality(self):
        # Test that __update_or_append_task correctly updates or appends tasks
        # Create a task first
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Task 1 [track::work] [severity::2]"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Task 1")
        self.assertEqual(result["tasks"][0]["severity"], "2.0")

        # Now add a new task with a different line and update the existing one
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 200.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Task 1 updated [track::work] [severity::3]",
            "- [ ] Task 2 [track::work]"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 2)

        # Tasks should be ordered based on their order in the file
        self.assertEqual(result["tasks"][0]["taskText"], "Task 1 updated")
        self.assertEqual(result["tasks"][0]["severity"], "3.0")
        self.assertEqual(result["tasks"][1]["taskText"], "Task 2")


if __name__ == "__main__":
    unittest.main()
