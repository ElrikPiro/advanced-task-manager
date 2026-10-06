import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch
from src.FileBroker import FileBroker
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, MissingTaskIdentityError
from src.wrappers.TimeManagement import TimePoint
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker
from src.taskmodels.ObsidianTaskModel import ObsidianTaskModel
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import (
    ObsidianVaultTaskJsonProvider,
    SnapshotRefreshRequiredError,
    VaultReadSnapshot,
)
from src.Utils import TaskDiscoveryPolicies
from src.Interfaces.IFileBroker import FileRegistry


class TestObsidianTaskProvider(unittest.TestCase):

    def setUp(self):
        self.mockTaskJsonProvider = MagicMock(spec=ITaskJsonProvider)
        self.mockFileBroker = MagicMock(spec=IFileBroker)
        policies = TaskDiscoveryPolicies(
            context_missing_policy="1",
            date_missing_policy="1",
            default_context="inbox",
            categories_prefixes=["work", "inbox"],
        )
        parser = ObsidianVaultTaskJsonProvider(
            self.mockFileBroker,
            policies,
            auto_start=False,
            disableThreading=True,
        )
        self.mockTaskJsonProvider.parseTaskFile.side_effect = parser.parseTaskFile

        def update_vault_lines(registry, path, updater):
            current = list(self.mockFileBroker.getVaultFileLines(registry, path))
            updated = updater(current)
            self.mockFileBroker.writeVaultFileLines(registry, path, list(updated))
            self.mockFileBroker.getVaultFileLines.return_value = list(updated)
            return list(updated)

        def update_file_content(registry, updater):
            current = self.mockFileBroker.readFileContent(registry)
            updated = updater(current)
            self.mockFileBroker.writeFileContent(registry, updated)
            self.mockFileBroker.readFileContent.return_value = updated
            return updated

        self.mockFileBroker.updateVaultFileLines.side_effect = update_vault_lines
        self.mockFileBroker.updateFileContent.side_effect = update_file_content
        self.provider = ObsidianTaskProvider(self.mockTaskJsonProvider, self.mockFileBroker, True)

    def tearDown(self):
        self.provider.dispose()

    def test_exportTasks(self):
        # Arrange
        currentTaskJson: dict = self.GetCurrentTaskJson()
        self.mockTaskJsonProvider.getJson.return_value = currentTaskJson

        # Act
        testClass = self.provider
        retval = testClass.exportTasks("json").decode("utf-8")

        # Assert
        self.assertEqual(testClass.lastJson, currentTaskJson)
        self.assertEqual(retval, self.fromObsidianToGenericJsonDumps(currentTaskJson))
        pass

    def test_getTaskList_reads_fresh_parse_without_running_discovery(self):
        task_json = self.GetCurrentTaskJson()
        open_task = dict(task_json["tasks"][0])
        open_task["taskText"] = "Open task"
        open_task["status"] = " "
        task_json["tasks"].append(open_task)
        self.mockTaskJsonProvider.getJson.return_value = task_json

        active = self.provider.getTaskList()
        all_tasks = self.provider.getTaskList(include_completed=True)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].getStatus(), " ")
        self.assertEqual(len(all_tasks), 2)
        self.assertEqual({task.getStatus() for task in all_tasks}, {" ", "x"})
        self.assertEqual(self.mockTaskJsonProvider.getJson.call_count, 2)
        self.mockTaskJsonProvider.discover.assert_not_called()

    def test_projection_snapshot_skips_write_fields_and_resolves_full_models_from_its_generation(self):
        current_lines = [
            "- [ ] Original [track::work] [id::projection-task]\n",
            "Captured detail from the original generation\n",
        ]
        current_signature = 100.0
        self.mockFileBroker.getVaultFiles.side_effect = lambda _: [("tasks.md", current_signature)]
        self.mockFileBroker.getVaultFileLines.side_effect = lambda _, __: list(current_lines)
        policies = TaskDiscoveryPolicies(
            context_missing_policy="0",
            date_missing_policy="0",
            default_context="inbox",
            categories_prefixes=["work", "inbox"],
        )
        json_provider = ObsidianVaultTaskJsonProvider(
            self.mockFileBroker,
            policies,
            auto_start=False,
            disableThreading=True,
        )
        task_provider = ObsidianTaskProvider(json_provider, self.mockFileBroker, True)
        try:
            json_provider.refresh()
            with patch.object(
                task_provider,
                "_ObsidianTaskProvider__getTaskSaveFields",
                side_effect=AssertionError("projection must not build write baselines"),
            ), patch.object(
                VaultReadSnapshot,
                "getTaskMetadata",
                side_effect=AssertionError("projection must not copy detail metadata"),
            ):
                projection = task_provider.getProjectionTaskListSnapshot(include_completed=True)

            self.assertEqual(projection.generation, 1)
            self.assertEqual(len(projection.tasks), 1)
            query_model = projection.tasks[0]
            self.assertFalse(hasattr(query_model, "_task_provider_baseline"))
            self.assertFalse(hasattr(query_model, "_provider_snapshot_metadata"))
            query_model.setDescription("Changed only in this projection")
            with self.assertRaises(SnapshotRefreshRequiredError):
                task_provider.saveTask(query_model)
            self.mockFileBroker.updateVaultFileLines.assert_not_called()

            current_lines = [
                "- [ ] Updated [track::work] [id::projection-task]\n",
                "Captured detail from the newer generation\n",
            ]
            current_signature = 101.0
            json_provider.refresh()

            resolved = projection.getTaskById("projection-task")
            self.assertEqual(resolved.getTaskText(), "Original")
            self.assertEqual(
                task_provider.getTaskMetadata(resolved),
                "".join([
                    "- [ ] Original [track::work] [id::projection-task]\n",
                    "Captured detail from the original generation\n",
                ]),
            )
            self.assertTrue(hasattr(resolved, "_task_provider_baseline"))
            self.assertTrue(hasattr(resolved, "_provider_snapshot_metadata"))
            self.assertEqual(query_model.getTaskText(), "Changed only in this projection")

            full_snapshot = task_provider.getTaskListSnapshot(include_completed=True)
            self.assertEqual(full_snapshot.generation, 2)
            self.assertEqual(full_snapshot.tasks[0].getTaskText(), "Updated")
            self.assertTrue(hasattr(full_snapshot.tasks[0], "_task_provider_baseline"))
            self.assertTrue(hasattr(full_snapshot.tasks[0], "_provider_snapshot_metadata"))
        finally:
            task_provider.dispose()

    def test_getTaskList_propagates_read_errors(self):
        self.mockTaskJsonProvider.getJson.side_effect = PermissionError("vault is unreadable")

        with self.assertRaisesRegex(PermissionError, "vault is unreadable"):
            self.provider.getTaskList()

    def test_discard_pending_task_reservations_is_noop(self):
        self.assertIsNone(self.provider.discardPendingTaskReservations())

    def test_saveTask_persists_fallback_and_preserves_unknown_vault_content(self):
        original_lines = [
            "---\n",
            "owner: planning\n",
            "---\n",
            "- [X] Original title [track:: work] [custom:: retain] [due:: 2026-10-06]\n",
            "%% Keep this note %%\n",
            "- [x] Completed task [track:: work]\n",
        ]
        self.mockFileBroker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mockFileBroker.getVaultFileLines.return_value = list(original_lines)
        task_id = fallback_task_id("Original title", "tasks.md", 3)
        task = ObsidianTaskModel(
            description="Original title",
            context="work",
            start=TimePoint.today().as_int(),
            due=TimePoint.today().as_int(),
            severity=2,
            totalCost=1,
            investedEffort=0,
            status="x",
            file="tasks.md",
            line=3,
            calm="true",
            raised=None,
            waited=None,
        )
        task.setDescription("Edited title")

        self.provider.saveTask(task)

        self.mockFileBroker.updateVaultFileLines.assert_called_once()
        args = self.mockFileBroker.writeVaultFileLines.call_args.args
        saved_lines = args[2]
        self.assertEqual(saved_lines[:3], original_lines[:3])
        self.assertIn("[custom:: retain]", saved_lines[3])
        self.assertIn(f"[id:: {task_id}]", saved_lines[3])
        self.assertTrue(saved_lines[3].startswith("- [X] Edited title"))
        self.assertEqual(saved_lines[4:], original_lines[4:])
        self.assertEqual(task.getTaskUID(), task_id)

    def test_saveTask_new_task_appends_with_prepared_id_and_keeps_completed_content(self):
        original = "# Personal tasks\n\n- [x] Keep completed [track:: work]\n"
        self.mockFileBroker.readFileContent.return_value = original
        self.mockFileBroker.getVaultFiles.return_value = []
        task = self.provider.createDefaultTask("New task")
        expected_id = fallback_task_id("New task", "ObsidianTaskProvider.md", 3)

        self.provider.saveTask(task)

        self.mockFileBroker.updateFileContent.assert_called_once_with(FileRegistry.OBSIDIAN_TASKS_MD, unittest.mock.ANY)
        saved_content = self.mockFileBroker.writeFileContent.call_args.args[1]
        self.assertTrue(saved_content.startswith(original))
        self.assertIn(f"[id:: {expected_id}]", saved_content)
        self.assertEqual(task.getTaskUID(), expected_id)
        self.assertEqual(task.getLine(), 3)

    def test_new_task_reservations_get_distinct_ids_before_writing(self):
        self.mockFileBroker.readFileContent.return_value = "# Personal tasks\n\n"
        self.mockFileBroker.getVaultFiles.return_value = []
        first = self.provider.createDefaultTask("First task")
        second = self.provider.createDefaultTask("Second task")

        self.assertNotEqual(first.getTaskUID(), second.getTaskUID())
        self.assertNotEqual(first.getLine(), second.getLine())

    def test_saveTask_rejects_missing_identity_without_writing(self):
        self.mockFileBroker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mockFileBroker.getVaultFileLines.return_value = ["- [ ] Existing [track:: work] [id:: existing]\n"]
        task = self._task_with_id("missing", file="tasks.md", line=0)

        with self.assertRaises(MissingTaskIdentityError):
            self.provider.saveTask(task)

        self.mockFileBroker.writeVaultFileLines.assert_not_called()

    def test_saveTask_rejects_duplicate_identity_before_writing(self):
        self.mockFileBroker.getVaultFiles.return_value = [("a.md", 100.0), ("b.md", 100.0)]
        self.mockFileBroker.getVaultFileLines.side_effect = lambda _, path: [
            f"- [ ] {path} [track:: work] [id:: duplicated]\n"
        ]
        task = self._task_with_id("duplicated", file="a.md", line=0)

        with self.assertRaises(AmbiguousTaskIdentityError):
            self.provider.saveTask(task)

        self.mockFileBroker.writeVaultFileLines.assert_not_called()

    def test_cached_identity_index_reserves_completed_task_with_invalid_task_metadata(self):
        contents = {
            "open.md": ["- [ ] Open [track::work] [id::duplicated]\n"],
            "completed.md": [
                "- [x] Completed but invalid metadata [track::work] "
                "[severity::not-a-number] [id::duplicated]\n"
            ],
        }
        files = [("open.md", 100.0), ("completed.md", 200.0)]
        self.mockFileBroker.getVaultFiles.side_effect = lambda _: list(files)
        self.mockFileBroker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])
        json_provider = ObsidianVaultTaskJsonProvider(
            self.mockFileBroker,
            TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="0",
                default_context="inbox",
                categories_prefixes=["work"],
            ),
            auto_start=False,
            disableThreading=True,
        )
        self.assertEqual([row["id"] for row in json_provider.getJson()["tasks"]], ["duplicated"])
        task_provider = ObsidianTaskProvider(json_provider, self.mockFileBroker, True)
        task = self._task_with_id("duplicated", file="open.md", line=0)

        with self.assertRaises(AmbiguousTaskIdentityError):
            task_provider.saveTask(task)

        self.mockFileBroker.updateVaultFileLines.assert_not_called()
        task_provider.dispose()

    def test_external_duplicate_after_snapshot_is_visible_on_refresh_not_save(self):
        contents = {
            "tasks.md": ["- [ ] Existing [track::work] [id::same-id]\n"],
        }
        files = [("tasks.md", 100.0)]
        self.mockFileBroker.getVaultFiles.side_effect = lambda _: list(files)
        self.mockFileBroker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])
        json_provider = ObsidianVaultTaskJsonProvider(
            self.mockFileBroker,
            TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="0",
                default_context="inbox",
                categories_prefixes=["work"],
            ),
            auto_start=False,
            disableThreading=True,
        )
        external_added = False

        def add_external_duplicate_then_update(registry, path, updater):
            nonlocal external_added
            if not external_added:
                contents["other.md"] = ["- [x] External [track::work] [id::same-id]\n"]
                files.append(("other.md", 200.0))
                external_added = True
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            self.mockFileBroker.writeVaultFileLines(registry, path, list(updated))
            return list(updated)

        self.mockFileBroker.updateVaultFileLines.side_effect = add_external_duplicate_then_update
        task_provider = ObsidianTaskProvider(json_provider, self.mockFileBroker, True)
        task = task_provider.getTaskById("same-id")
        task.setDescription("Edited")

        task_provider.saveTask(task)

        self.assertIn("Edited", contents["tasks.md"][0])
        self.assertEqual(contents["other.md"], ["- [x] External [track::work] [id::same-id]\n"])
        json_provider.refresh()
        with self.assertRaises(AmbiguousTaskIdentityError):
            json_provider.getTaskById("same-id")
        self.mockFileBroker.writeVaultFileLines.assert_called_once()
        task_provider.dispose()

    def test_external_duplicate_with_restored_mtime_is_visible_on_refresh_not_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            appdata = root / "appdata"
            vault = root / "vault"
            data.mkdir()
            appdata.mkdir()
            vault.mkdir()
            target = vault / "tasks.md"
            external = vault / "other.md"
            target_original = "- [ ] Existing [track::work] [id::same-id]\n"
            target.write_text(target_original, encoding="utf-8")
            external.write_text("- [ ] External [track::work] [id::otherid]\n", encoding="utf-8")
            broker = FileBroker(str(data), str(appdata), str(vault))
            json_provider = ObsidianVaultTaskJsonProvider(
                broker,
                TaskDiscoveryPolicies(
                    context_missing_policy="0",
                    date_missing_policy="0",
                    default_context="inbox",
                    categories_prefixes=["work"],
                ),
                auto_start=False,
                disableThreading=True,
            )
            task_provider = ObsidianTaskProvider(json_provider, broker, True)
            task = task_provider.getTaskById("same-id")
            task.setDescription("Edited")
            previous_stat = external.stat()
            original_update = broker.updateVaultFileLines

            def change_external_id_and_update(registry, relative_path, updater):
                if relative_path == "tasks.md":
                    time.sleep(0.01)
                    external.write_text(
                        "- [ ] External [track::work] [id::same-id]\n",
                        encoding="utf-8",
                    )
                    os.utime(
                        external,
                        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns),
                    )
                return original_update(registry, relative_path, updater)

            with patch.object(
                broker,
                "updateVaultFileLines",
                side_effect=change_external_id_and_update,
            ):
                task_provider.saveTask(task)

            self.assertEqual(external.stat().st_mtime_ns, previous_stat.st_mtime_ns)
            self.assertEqual(external.stat().st_size, previous_stat.st_size)
            self.assertNotEqual(external.stat().st_ctime_ns, previous_stat.st_ctime_ns)
            self.assertIn("Edited", target.read_text(encoding="utf-8"))
            json_provider.refresh()
            with self.assertRaises(AmbiguousTaskIdentityError):
                json_provider.getTaskById("same-id")
            task_provider.dispose()

    def _task_with_id(self, task_id: str, *, file: str, line: int) -> ObsidianTaskModel:
        return ObsidianTaskModel(
            description="Existing",
            context="work",
            start=TimePoint.today().as_int(),
            due=TimePoint.today().as_int(),
            severity=1,
            totalCost=1,
            investedEffort=0,
            status=" ",
            file=file,
            line=line,
            calm="false",
            raised=None,
            waited=None,
            task_id=task_id,
        )

    def GetCurrentTaskJson(self) -> dict:
        return {
            "tasks": [
                {
                    "taskText": "Task 1",
                    "track": "track 1",
                    "starts": "1741906800000",
                    "due": TimePoint.today().as_int(),
                    "severity": "1",
                    "total_cost": "1",
                    "effort_invested": "1",
                    "status": "x",
                    "file": "file 1",
                    "line": "1",
                    "calm": "true"
                }
            ],
        }

    def fromObsidianToGenericJsonDumps(self, obsidianJson: dict) -> str:
        retval = {
            "tasks": [],
        }

        for task in obsidianJson["tasks"]:
            slash = "/"
            dot = "."
            text = task["taskText"]
            _file = task["file"]
            _line = task["line"]

            hash_input = f"{text}{_file}{_line}"
            task_uid = hashlib.md5(hash_input.encode()).hexdigest()[0:5]

            retval["tasks"].append({
                "id": hashlib.md5(hash_input.encode()).hexdigest(),
                "description": f"({task['track']}) {text} @ '{_file.split(slash).pop().split(dot)[0]}:{_line}' [{task_uid}]",
                "context": task["track"],
                "start": str(int(task["starts"])),
                "due": str(int(task["due"])),
                "severity": str(float(task["severity"])),
                "totalCost": str(float(task["total_cost"])),
                "investedEffort": str(float(task["effort_invested"])),
                "status": task["status"],
                "calm": str(bool(task["calm"]))
            })

        return bytearray(json.dumps(retval, indent=4), "utf-8").decode("utf-8")


if __name__ == '__main__':
    unittest.main()
