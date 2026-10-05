import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry, VaultRegistry
from src.Interfaces.IFileBroker import IFileBroker
from src.Utils import TaskDiscoveryPolicies
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.taskjsonproviders.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.taskproviders.TaskProvider import TaskProvider
from src.wrappers.TimeManagement import TimePoint


class ProviderDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.json_path = os.path.join(self.tempdir.name, "json")
        self.appdata_path = os.path.join(self.tempdir.name, "appdata")
        self.vault_path = os.path.join(self.tempdir.name, "vault")
        self.file_broker = FileBroker(self.json_path, self.appdata_path, self.vault_path)

    def snapshot(self, root: str) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        for directory, _, filenames in os.walk(root):
            for filename in filenames:
                path = os.path.join(directory, filename)
                with open(path, "rb") as file:
                    result[os.path.relpath(path, root)] = file.read()
        return result

    def write_file(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    def test_repeated_reads_of_absent_storage_do_not_create_files(self):
        os.makedirs(self.tempdir.name, exist_ok=True)
        before = self.snapshot(self.tempdir.name)
        self.assertEqual(before, {})

        json_provider = TaskJsonProvider(self.file_broker)
        task_provider = TaskProvider(json_provider, self.file_broker, disableThreading=True)
        obsidian_json_provider = ObsidianVaultTaskJsonProvider(
            self.file_broker,
            TaskDiscoveryPolicies("0", "1", "inbox", ["work"])
        )
        obsidian_task_provider = ObsidianTaskProvider(
            obsidian_json_provider,
            self.file_broker,
            disableThreading=True
        )

        for _ in range(2):
            self.assertEqual(self.file_broker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON), '{"tasks": []}')
            self.assertEqual(self.file_broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON), {"tasks": []})
            self.assertEqual(self.file_broker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON), {"tasks": []})
            self.assertEqual(self.file_broker.readFileContentJson(FileRegistry.LAST_RECEIVED_FILE), {"tasks": []})
            self.assertEqual(self.file_broker.readStatisticsFileContentJson(), {"log": []})
            self.assertEqual(self.file_broker.getVaultFiles(VaultRegistry.OBSIDIAN), [])
            with self.assertRaises(FileNotFoundError):
                self.file_broker.getVaultFileLines(VaultRegistry.OBSIDIAN, "absent.md")
            self.assertEqual(task_provider.getTaskList(), [])
            self.assertEqual(task_provider.getTaskListAttribute("projects"), [])
            self.assertEqual(obsidian_task_provider.getTaskList(), [])
            self.assertEqual(obsidian_task_provider.getTaskListAttribute("projects"), [])

        self.assertEqual(self.snapshot(self.tempdir.name), before)

    def test_invalid_json_remains_untouched_after_repeated_provider_reads(self):
        tasks_path = os.path.join(self.json_path, "tasks.json")
        self.write_file(tasks_path, "{ this is invalid")
        before = self.snapshot(self.json_path)
        provider = TaskJsonProvider(self.file_broker)

        for _ in range(2):
            with self.assertRaises(json.JSONDecodeError):
                provider.getJson()

        self.assertEqual(self.snapshot(self.json_path), before)

    def test_dataview_provider_does_not_turn_unexpected_payloads_into_empty_success(self):
        file_broker = MagicMock(spec=IFileBroker)
        file_broker.readFileContentJson.return_value = []
        provider = ObsidianDataviewTaskJsonProvider(file_broker)

        with self.assertRaisesRegex(TypeError, "top level"):
            provider.getJson()

    def test_json_get_is_pure_and_explicit_discovery_is_idempotent(self):
        tasks_path = os.path.join(self.json_path, "tasks.json")
        source = {
            "tasks": [
                {"description": "Finished", "project": "Release", "status": "x"}
            ],
            "projects": [
                {"name": "Release", "status": "open"},
                {"name": "Archive", "status": "closed"},
                {"name": "Paused", "status": "on-hold"}
            ]
        }
        self.write_file(tasks_path, json.dumps(source, indent=2))
        provider = TaskJsonProvider(self.file_broker)
        before = self.snapshot(self.json_path)

        first_read = provider.getJson()
        second_read = provider.getJson()
        self.assertEqual(first_read, source)
        self.assertEqual(second_read, source)
        self.assertEqual(self.snapshot(self.json_path), before)

        discovered = provider.discover()
        self.assertEqual(len(discovered["tasks"]), 2)
        action = discovered["tasks"][1]
        self.assertEqual(action["description"], "Define next action")
        self.assertEqual(action["project"], "Release")
        self.assertEqual(action["context"], "alert")
        after_discovery = self.snapshot(self.json_path)
        self.assertNotEqual(after_discovery, before)

        self.assertEqual(provider.getJson(), discovered)
        self.assertEqual(provider.discover(), discovered)
        self.assertEqual(self.snapshot(self.json_path), after_discovery)

    def test_markdown_get_parses_frontmatter_and_completed_tasks_without_writes(self):
        self.write_file(
            os.path.join(self.vault_path, "EmptyOpen.md"),
            "---\nproject: open\ntrack: work\nstarts: 2026-10-04T10:30\ndue: 2026-10-04T12:15\nseverity: 3\n---\n# Empty project\n"
        )
        self.write_file(
            os.path.join(self.vault_path, "Completed.md"),
            "---\nproject: open\ntrack: work\n---\n- [x] Finished [raised:: release]\n"
        )
        self.write_file(
            os.path.join(self.vault_path, "Open.md"),
            "---\nproject: open\ntrack: work\n---\n- [ ] Existing action [track::work]\n"
        )
        self.write_file(
            os.path.join(self.vault_path, "Closed.md"),
            "---\nproject: closed\ntrack: work\n---\n"
        )
        self.write_file(
            os.path.join(self.vault_path, "OnHold.md"),
            "---\nproject: on-hold\ntrack: work\n---\n"
        )
        provider = ObsidianVaultTaskJsonProvider(
            self.file_broker,
            TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="1",
                default_context="inbox",
                categories_prefixes=["work"]
            )
        )
        before = self.snapshot(self.vault_path)

        first_read = provider.getJson()
        second_read = provider.getJson()
        task_provider = ObsidianTaskProvider(provider, self.file_broker, disableThreading=True)
        task_view = task_provider.getTaskList()
        project_view = task_provider.getTaskListAttribute("projects")
        self.assertEqual(first_read, second_read)
        self.assertEqual(len(task_view), 1)
        self.assertEqual(project_view, first_read["projects"])
        self.assertEqual(self.snapshot(self.vault_path), before)
        self.assertEqual({project["status"] for project in first_read["projects"]}, {"open", "closed", "on-hold"})
        self.assertEqual(len(first_read["tasks"]), 2)
        completed = next(task for task in first_read["tasks"] if task["taskText"] == "Finished")
        self.assertEqual(completed["status"], "x")
        self.assertEqual(completed["raised"], "release")
        existing = next(task for task in first_read["tasks"] if task["taskText"] == "Existing action")
        self.assertEqual(existing["status"], " ")

        empty_open = next(project for project in first_read["projects"] if project["name"] == "EmptyOpen")
        self.assertEqual(empty_open["status"], "open")

    def test_markdown_discovery_adds_only_uncovered_open_project_actions_once(self):
        contents = {
            "EmptyOpen.md": "---\nproject: open\ntrack: work\nstarts: 2026-10-04T10:30\ndue: 2026-10-04T12:15\nseverity: 3\n---\n# Empty project\n",
            "Completed.md": "---\nproject: open\ntrack: work\n---\n- [x] Finished [track::work]\n",
            "Open.md": "---\nproject: open\ntrack: work\n---\n- [ ] Existing action [track::work]\n",
            "Closed.md": "---\nproject: closed\ntrack: work\n---\n",
            "OnHold.md": "---\nproject: on-hold\ntrack: work\n---\n"
        }
        for path, content in contents.items():
            self.write_file(os.path.join(self.vault_path, path), content)
        provider = ObsidianVaultTaskJsonProvider(
            self.file_broker,
            TaskDiscoveryPolicies("0", "1", "inbox", ["work"])
        )

        before = self.snapshot(self.vault_path)
        pure_read = provider.getJson()
        self.assertFalse(any(task["taskText"] == "Define next action" for task in pure_read["tasks"]))
        self.assertEqual(self.snapshot(self.vault_path), before)

        discovered = provider.discover()
        after_discovery = self.snapshot(self.vault_path)
        actions = [task for task in discovered["tasks"] if task["taskText"] == "Define next action"]
        self.assertEqual(len(actions), 2)
        action_by_project = {task["file"]: task for task in actions}
        empty_action = action_by_project["EmptyOpen.md"]
        self.assertEqual(empty_action["starts"], str(TimePoint.from_string("2026-10-04T10:30").as_int()))
        self.assertEqual(empty_action["due"], str(TimePoint.from_string("2026-10-04T12:15").as_int()))
        self.assertEqual(empty_action["severity"], "3.0")
        for filename in ("Open.md", "Closed.md", "OnHold.md"):
            with open(os.path.join(self.vault_path, filename), encoding="utf-8") as file:
                self.assertNotIn("Define next action", file.read())
        for filename in ("EmptyOpen.md", "Completed.md"):
            with open(os.path.join(self.vault_path, filename), encoding="utf-8") as file:
                self.assertIn("Define next action", file.read())
        self.assertNotEqual(after_discovery, before)

        provider.discover()
        self.assertEqual(self.snapshot(self.vault_path), after_discovery)

    def test_concurrent_markdown_reads_return_independent_snapshots(self):
        file_broker = MagicMock(spec=IFileBroker)
        file_broker.getVaultFiles.return_value = [("First.md", 1.0), ("Second.md", 2.0)]
        read_barrier = threading.Barrier(2)

        def read_file_lines(registry, path):
            read_barrier.wait(timeout=5)
            return ["---\n", "---\n", f"- [ ] {path} task [track::work]\n"]

        file_broker.getVaultFileLines.side_effect = read_file_lines
        provider = ObsidianVaultTaskJsonProvider(
            file_broker,
            TaskDiscoveryPolicies("0", "1", "inbox", ["work"])
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(provider.getJson)
            second = executor.submit(provider.getJson)
            first_result = first.result(timeout=10)
            second_result = second.result(timeout=10)

        expected = {"First.md", "Second.md"}
        for result in (first_result, second_result):
            self.assertEqual({task["file"] for task in result["tasks"]}, expected)
            self.assertEqual(len(result["tasks"]), 2)
            self.assertEqual(result["projects"], [])


if __name__ == "__main__":
    unittest.main()
