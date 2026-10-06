import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, call, patch
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

    def test_getJson_reuses_unchanged_file_parse_without_discovery(self):
        self.mock_file_broker.getVaultFiles.return_value = [("test.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = ["---", "---"]
        self.provider.getJson()

        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.provider.getJson()
        self.mock_file_broker.getVaultFileLines.assert_not_called()

    def test_getJson_cache_tracks_inventory_mtime_and_returns_detached_results(self):
        files = [("one.md", 100.0), ("two.md", 100.0)]
        contents = {
            "one.md": ["---", "project: open", "---", "- [ ] One [track::work]"],
            "two.md": ["---", "project: open", "---", "- [x] Two [track::work]"],
            "three.md": ["- [ ] Three [track::work]"],
        }
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])

        first = self.provider.getJson()
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)
        self.assertEqual([task["taskText"] for task in first["tasks"]], ["One", "Two"])
        self.assertEqual(first["tasks"][1]["status"], "x")
        self.assertEqual([project["path"] for project in first["projects"]], ["one.md", "two.md"])
        first["tasks"][0]["taskText"] = "poisoned caller result"
        first["projects"][0]["status"] = "held"

        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.mock_file_broker.getVaultFiles.reset_mock()
        unchanged = self.provider.getJson()
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.mock_file_broker.getVaultFileLines.assert_not_called()
        self.assertEqual(unchanged["tasks"][0]["taskText"], "One")
        self.assertEqual(unchanged["projects"][0]["status"], "open")

        contents["one.md"] = ["---", "project: closed", "---", "- [x] One [track::work]"]
        files = [("one.md", 101.0), ("three.md", 100.0)]
        self.mock_file_broker.getVaultFiles.reset_mock()
        changed = self.provider.getJson()
        self.assertEqual(
            [call.args[1] for call in self.mock_file_broker.getVaultFileLines.call_args_list],
            ["one.md", "three.md"],
        )
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.assertEqual([task["taskText"] for task in changed["tasks"]], ["One", "Three"])
        self.assertEqual(changed["tasks"][0]["status"], "x")
        self.assertEqual(changed["projects"], [{"name": "one", "status": "closed", "path": "one.md"}])

        # A rename is a new path even when the replacement has the old mtime;
        # deleted paths disappear from the snapshot and unchanged paths reuse
        # their parsed values.
        contents["renamed.md"] = ["---", "project: open", "---", "- [x] Renamed [track::work]"]
        files = [("one.md", 101.0), ("renamed.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.mock_file_broker.getVaultFiles.reset_mock()
        renamed = self.provider.getJson()
        self.assertEqual(
            [call.args[1] for call in self.mock_file_broker.getVaultFileLines.call_args_list],
            ["renamed.md"],
        )
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.assertEqual([task["taskText"] for task in renamed["tasks"]], ["One", "Renamed"])
        self.assertEqual(renamed["tasks"][1]["status"], "x")
        self.assertEqual(
            [(project["path"], project["status"]) for project in renamed["projects"]],
            [("one.md", "closed"), ("renamed.md", "open")],
        )

    def test_getJson_refreshes_default_dates_when_local_day_changes(self):
        self.mock_file_broker.getVaultFiles.return_value = [("today.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = ["- [ ] Today [track::work]"]
        first_day = TimePoint.from_string("2026-10-06")
        next_day = TimePoint.from_string("2026-10-07")

        with patch.object(TimePoint, "today", return_value=first_day):
            first = self.provider.getJson()
        with patch.object(TimePoint, "today", return_value=next_day):
            next_snapshot = self.provider.getJson()

        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)
        self.assertEqual(first["tasks"][0]["starts"], str(first_day.as_int()))
        self.assertEqual(first["tasks"][0]["due"], str(first_day.as_int()))
        self.assertEqual(next_snapshot["tasks"][0]["starts"], str(next_day.as_int()))
        self.assertEqual(next_snapshot["tasks"][0]["due"], str(next_day.as_int()))

    def test_failed_changed_file_read_does_not_publish_partial_snapshot(self):
        files = [("tasks.md", 100.0)]
        contents = ["- [ ] Original [track::work]"]
        fail_read = False
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)

        def read_lines(_, path):
            if fail_read:
                raise OSError("temporary read failure")
            return list(contents)

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        original = self.provider.getJson()
        self.assertEqual(original["tasks"][0]["taskText"], "Original")

        files = [("tasks.md", 101.0)]
        contents[:] = ["- [ ] Updated [track::work]"]
        fail_read = True
        with self.assertRaisesRegex(OSError, "temporary read failure"):
            self.provider.getJson()

        fail_read = False
        recovered = self.provider.getJson()
        self.assertEqual(recovered["tasks"][0]["taskText"], "Updated")
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 3)

    def test_file_invalidation_prevents_pending_old_read_from_publishing(self):
        contents = ["- [ ] Before [track::work]"]
        read_started = Event()
        release_read = Event()
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]

        def read_lines(_, __):
            snapshot = list(contents)
            read_started.set()
            if not release_read.wait(timeout=5):
                raise TimeoutError("test read barrier timed out")
            return snapshot

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending_read = executor.submit(self.provider.getJson)
            self.assertTrue(read_started.wait(timeout=5))
            self.provider._ObsidianVaultTaskJsonProvider__invalidate_cached_file("tasks.md")
            contents[:] = ["- [ ] After [track::work]"]
            release_read.set()
            old_result = pending_read.result(timeout=5)

        self.assertEqual(old_result["tasks"][0]["taskText"], "Before")
        fresh_result = self.provider.getJson()
        self.assertEqual(fresh_result["tasks"][0]["taskText"], "After")
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)

    def test_discovery_generates_initial_action_then_reuses_warm_snapshot(self):
        files = [("project.md", 100.0)]
        contents = {"project.md": ["---", "project: open", "track: work", "---", "# Project"]}
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])

        def update_lines(_, path, updater):
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            files[:] = [(current_path, mtime + 1.0 if current_path == path else mtime) for current_path, mtime in files]
            return list(updated)

        self.mock_file_broker.updateVaultFileLines.side_effect = update_lines

        first = self.provider.discover()
        self.assertEqual(
            [task["taskText"] for task in first["tasks"]],
            ["Define next action"],
        )
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)

        self.mock_file_broker.getVaultFileLines.reset_mock()
        second = self.provider.discover()
        self.assertEqual([task["taskText"] for task in second["tasks"]], ["Define next action"])
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 1)

        self.mock_file_broker.getVaultFiles.reset_mock()
        self.mock_file_broker.getVaultFileLines.reset_mock()
        third = self.provider.discover()
        self.assertEqual([task["taskText"] for task in third["tasks"]], ["Define next action"])
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.mock_file_broker.getVaultFileLines.assert_not_called()

    def test_failed_discovery_is_retried_and_changed_project_still_gets_action(self):
        files = [("existing.md", 100.0), ("new.md", 200.0)]
        contents = {
            "existing.md": [
                "---", "project: open", "track: work", "---",
                "- [ ] Existing [track::work]",
            ],
            "new.md": ["---", "project: closed", "track: work", "---", "# New project"],
        }
        fail_new_project_read = False
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)

        def read_lines(_, path):
            if path == "new.md" and fail_new_project_read:
                raise OSError("temporary project read failure")
            return list(contents[path])

        def update_lines(_, path, updater):
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            files[:] = [(current_path, mtime + 1.0 if current_path == path else mtime) for current_path, mtime in files]
            return list(updated)

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        self.mock_file_broker.updateVaultFileLines.side_effect = update_lines
        self.provider.discover()

        contents["new.md"] = ["---", "project: open", "track: work", "---", "# New project"]
        files[:] = [(path, mtime + 1.0 if path == "new.md" else mtime) for path, mtime in files]
        self.provider.getJson()  # Cache the new inventory before discovery fails.
        fail_new_project_read = True
        with self.assertRaisesRegex(OSError, "temporary project read failure"):
            self.provider.discover()

        fail_new_project_read = False
        self.mock_file_broker.getVaultFileLines.reset_mock()
        retried = self.provider.discover()

        self.assertTrue(any(task["file"] == "new.md" and task["taskText"] == "Define next action" for task in retried["tasks"]))
        self.assertGreater(self.mock_file_broker.getVaultFileLines.call_count, 0)

    def test_external_project_added_during_discovery_is_reconciled_next_time(self):
        files = [("existing.md", 100.0)]
        contents = {
            "existing.md": [
                "---", "project: open", "track: work", "---",
                "- [ ] Existing [track::work]",
            ],
            "new.md": ["---", "project: open", "track: work", "---", "# New project"],
        }
        external_change_added = False
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)

        def read_lines(_, path):
            nonlocal external_change_added
            if path == "existing.md" and not external_change_added:
                files.append(("new.md", 200.0))
                external_change_added = True
            return list(contents[path])

        def update_lines(_, path, updater):
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            files[:] = [(current_path, mtime + 1.0 if current_path == path else mtime) for current_path, mtime in files]
            return list(updated)

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        self.mock_file_broker.updateVaultFileLines.side_effect = update_lines

        self.provider.discover()
        retried = self.provider.discover()

        self.assertTrue(any(task["file"] == "new.md" and task["taskText"] == "Define next action" for task in retried["tasks"]))

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

    def test_file_header_accepts_double_colon_and_preserves_value_colons(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "project:: open\n",
            "track:: work\n",
            "severity:: 2\n",
            "remaining_cost:: 4\n",
            "invested:: 1\n",
            "starts: 2023-12-31T23:45\n",
            "source: https://example.test/a:b\n",
            "---\n",
            "- [ ] Task [due::2024-01-01]\n",
        ]

        result = self.provider.getJson()
        task = result["tasks"][0]

        self.assertEqual(task["track"], "work")
        self.assertEqual(task["severity"], "2.0")
        self.assertEqual(task["remaining_cost"], "4")
        self.assertEqual(task["invested"], "1")
        self.assertEqual(task["total_cost"], "3.0")
        self.assertEqual(task["starts"], str(TimePoint.from_string("2023-12-31T23:45").as_int()))
        self.assertEqual(task["source"], "https://example.test/a:b")
        self.assertEqual(result["projects"], [{"name": "tasks", "status": "open", "path": "tasks.md"}])

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
