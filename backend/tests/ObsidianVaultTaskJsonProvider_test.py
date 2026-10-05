import unittest
from unittest.mock import MagicMock
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, VaultRegistry
from src.wrappers.TimeManagement import TimePoint
from src.Utils import TaskDiscoveryPolicies
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError


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

        def update_vault_lines(registry, path, updater):
            current = list(self.mock_file_broker.getVaultFileLines(registry, path))
            updated = updater(current)
            self.mock_file_broker.writeVaultFileLines(registry, path, list(updated))
            self.mock_file_broker.getVaultFileLines.return_value = list(updated)
            return list(updated)

        self.mock_file_broker.updateVaultFileLines.side_effect = update_vault_lines

    def test_empty_vault_returns_empty_task_and_project_lists(self):
        self.mock_file_broker.getVaultFiles.return_value = []
        result = self.provider.getJson()
        self.assertEqual(result, {"tasks": [], "projects": []})
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)

    def test_getJson_re_reads_vault_without_discovery(self):
        self.mock_file_broker.getVaultFiles.return_value = [("test.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = ["---", "---"]
        self.provider.getJson()

        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.provider.getJson()
        self.mock_file_broker.getVaultFileLines.assert_called_once_with(VaultRegistry.OBSIDIAN, "test.md")

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

        # Reading parses the project but leaves next-action reconciliation to discover().
        self.assertEqual(len(result["tasks"]), 0)
        self.mock_file_broker.writeVaultFileLines.assert_not_called()

    def test_discover_persists_next_action_for_open_empty_project(self):
        files = [("project.md", 100.0)]
        contents = {"project.md": ["---\n", "project: open\n", "---\n", "# Project Title\n"]}
        self.mock_file_broker.getVaultFiles.return_value = files
        self.mock_file_broker.getVaultFileLines.side_effect = lambda registry, path: list(contents[path])

        def write_file(registry, path, lines):
            contents[path] = list(lines)

        self.mock_file_broker.writeVaultFileLines.side_effect = write_file

        result = self.provider.discover()

        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Define next action")
        self.assertEqual(result["tasks"][0]["track"], "work")
        self.assertIn("Define next action", "".join(contents["project.md"]))
        self.assertIn(f"[id::{fallback_task_id('Define next action', 'project.md', 4)}]", contents["project.md"][4])
        self.mock_file_broker.updateVaultFileLines.assert_called_once()
        self.mock_file_broker.writeVaultFileLines.assert_called_once()

    def test_discover_rejects_a_generated_identifier_already_in_the_vault(self):
        duplicate_id = fallback_task_id("Define next action", "project.md", 4)
        files = [("project.md", 100.0), ("other.md", 200.0)]
        contents = {
            "project.md": ["---\n", "project: open\n", "---\n", "# Project\n"],
            "other.md": [f"- [ ] Existing [track::work] [id::{duplicate_id}]\n"],
        }
        self.mock_file_broker.getVaultFiles.return_value = files
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])

        with self.assertRaises(AmbiguousTaskIdentityError):
            self.provider.discover()

        self.mock_file_broker.updateVaultFileLines.assert_called_once()
        self.mock_file_broker.writeVaultFileLines.assert_not_called()

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

    def test_frontmatter_datetime_keeps_hour_and_minute_colons(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "project: open\n",
            "starts: 2023-12-31T23:45\n",
            "due: 2024-01-01T01:15\n",
            "---\n",
            "- [ ] Task [track::work]\n"
        ]

        task = self.provider.getJson()["tasks"][0]
        self.assertEqual(task["starts"], str(TimePoint.from_string("2023-12-31T23:45").as_int()))
        self.assertEqual(task["due"], str(TimePoint.from_string("2024-01-01T01:15").as_int()))

    def test_completed_checkbox_is_parsed_for_complete_task_queries(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "---\n",
            "- [x] Finished [track::work]\n"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["status"], "x")

    def test_task_line_identity_is_read_as_an_opaque_value(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "---\n",
            "- [ ] Task [track::work] [id::opaque/id:7] [extra:: keep]\n",
        ]

        task = self.provider.getJson()["tasks"][0]

        self.assertEqual(task["id"], "opaque/id:7")

    def test_empty_task_line_identity_is_rejected(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task [track::work] [id::   ]\n",
        ]

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()

    def test_conflicting_task_line_identities_are_rejected(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task [track::work] [id::first] [id::second]\n",
        ]

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()

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

    def test_read_failure_during_file_processing_is_propagated(self):
        self.mock_file_broker.getVaultFiles.return_value = [("valid.md", 100.0), ("invalid.md", 200.0)]

        def mock_get_file_lines(registry, path):
            if path == "valid.md":
                return ["- [ ] Valid task [track::work]"]
            else:
                raise Exception("Test error")

        self.mock_file_broker.getVaultFileLines.side_effect = mock_get_file_lines

        # A failed read must not be reported as a successful partial/empty view.
        with self.assertRaisesRegex(Exception, "Test error"):
            self.provider.getJson()

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
