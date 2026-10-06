"""Real-file integration checks for atomic persistence and partial outcomes."""

import copy
import datetime
import json
import os
import stat
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from src.AtomicFileStore import AtomicFileStore, AtomicWriteError
from src.FileBroker import FileBroker
from src.HeuristicScheduling import HeuristicScheduling
from src.StatisticsService import StatisticsService
from src.TelegramTaskListManager import TelegramTaskListManager
from src.Utils import TaskDiscoveryPolicies, WorkLogEntry
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import (
    AmbiguousResourceError,
    OperationFailedError,
    ResourceNotFoundError,
)
from src.MutationCoordinator import OperationExecutionError
from src.domain.models import OperationTarget
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import (
    ObsidianVaultTaskJsonProvider,
    SnapshotRefreshRequiredError,
)
from src.taskproviders.TaskIdentityErrors import MissingTaskIdentityError
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.taskproviders.TaskProvider import TaskProvider
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class AtomicPersistenceIntegrationTest(TestCase):
    """Exercise atomic persistence through providers on a local temporary FS."""

    TASK_ID = "task-1"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.data_dir = root / "data"
        self.data_dir.mkdir()
        self.vault_dir = root / "vault"
        self.vault_dir.mkdir()
        self.tasks_path = self.data_dir / "tasks.json"
        self.statistics_path = self.data_dir / "statistics.json"
        self._write_tasks([self._task_record()])

        self.file_broker = FileBroker(str(self.data_dir), str(root / "appdata"), str(self.vault_dir))
        self.file_broker.cleanupAtomicTemps([str(self.data_dir), str(self.vault_dir)])
        self.task_json_provider = TaskJsonProvider(self.file_broker)
        self.task_provider = TaskProvider(self.task_json_provider, self.file_broker, disableThreading=True)
        self.statistics = StatisticsService(
            self.file_broker,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )
        self.statistics.initialize()
        self.task_list_manager = TelegramTaskListManager([], [], [], [], self.statistics)
        self.application = TaskApplicationService(
            self.task_provider,
            scheduling=None,
            statistics_service=self.statistics,
            task_list_manager=self.task_list_manager,
            categories=[{"prefix": "work"}],
        )

    @staticmethod
    def _task_record(*, task_id: str = TASK_ID, description: str = "Plan release") -> dict[str, object]:
        now = TimePoint.now().as_int()
        return {
            "id": task_id,
            "description": description,
            "context": "work:operations",
            "start": str(now),
            "due": str(now + 90 * 86_400_000),
            "severity": "1.0",
            "totalCost": "8.0",
            "investedEffort": "2.0",
            "status": " ",
            "calm": "False",
            "project": "",
            "unknownTaskField": {"retain": True},
        }

    def _write_tasks(self, tasks: list[dict[str, object]]) -> None:
        self.tasks_path.write_text(
            json.dumps({"unknownTopLevel": {"retain": "external"}, "tasks": tasks}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _file_fsync_failure(fail_on: int = 1):
        original_fsync = os.fsync
        count = 0

        def fail(fd: int) -> None:
            nonlocal count
            if stat.S_ISREG(os.fstat(fd).st_mode):
                count += 1
                if count == fail_on:
                    raise OSError("injected file fsync failure")
            original_fsync(fd)

        return patch("src.AtomicFileStore.os.fsync", side_effect=fail)

    def test_file_failure_before_replace_is_known_unchanged_and_does_not_publish(self) -> None:
        original_bytes = self.tasks_path.read_bytes()
        self.application.read_task(self.TASK_ID)
        original_cache = copy.deepcopy(self.task_provider.dict_task_list)

        with self._file_fsync_failure(), self.assertRaises(OperationFailedError) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        self.assertEqual(caught.exception.effects_state, "none")
        self.assertEqual(caught.exception.details.get("failed_id"), self.TASK_ID)
        self.assertEqual(caught.exception.details.get("write_phase"), "file_fsync")
        self.assertEqual(caught.exception.details.get("write_replaced"), "false")
        self.assertEqual(self.tasks_path.read_bytes(), original_bytes)
        self.assertEqual(self.task_provider.dict_task_list, original_cache)
        self.assertEqual(list(self.data_dir.glob(".elrik-atomic-*.tmp")), [])

    def test_failure_after_task_replace_reports_unknown_without_publishing_cache(self) -> None:
        self.application.read_task(self.TASK_ID)
        original_cache = copy.deepcopy(self.task_provider.dict_task_list)
        original_fsync = os.fsync
        replace_returned = False
        original_replace = os.replace

        def mark_replace(source, destination):
            nonlocal replace_returned
            result = original_replace(source, destination)
            replace_returned = True
            return result

        def fail_directory_sync(fd: int) -> None:
            if replace_returned and stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected directory fsync failure")
            original_fsync(fd)

        with patch("src.AtomicFileStore.os.replace", side_effect=mark_replace), patch(
            "src.AtomicFileStore.os.fsync", side_effect=fail_directory_sync
        ), self.assertRaises(OperationFailedError) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertEqual(caught.exception.details.get("uncertain_id"), self.TASK_ID)
        self.assertEqual(caught.exception.details.get("write_replaced"), "true")
        stored_task = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(stored_task["description"], "Updated release")
        self.assertEqual(self.task_provider.dict_task_list, original_cache)

    def test_post_commit_identity_refresh_error_keeps_write_state_unknown(self) -> None:
        original_save = self.task_provider.saveTask

        def save_then_lose_confirmation(task) -> None:
            original_save(task)
            error = MissingTaskIdentityError("post-commit identity refresh failed")
            error.effects_state = "unknown"
            raise error

        with patch.object(self.task_provider, "saveTask", side_effect=save_then_lose_confirmation), self.assertRaises(
            ResourceNotFoundError
        ) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertEqual(caught.exception.details.get("uncertain_id"), self.TASK_ID)
        self.assertEqual(
            json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]["description"],
            "Updated release",
        )

    def test_json_refresh_failure_after_replace_is_unknown_and_does_not_publish_cache(self) -> None:
        original_cache = copy.deepcopy(self.task_provider.dict_task_list)
        create_task = self.task_provider.createTaskFromDict
        creations = 0

        def fail_on_confirmed_refresh(*args, **kwargs):
            nonlocal creations
            creations += 1
            if creations == 3:
                raise ValueError("injected confirmed JSON refresh failure")
            return create_task(*args, **kwargs)

        with patch.object(
            self.task_provider,
            "createTaskFromDict",
            side_effect=fail_on_confirmed_refresh,
        ), self.assertRaises(OperationFailedError) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        self.assertEqual(creations, 3)
        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertEqual(caught.exception.details.get("uncertain_id"), self.TASK_ID)
        stored = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(stored["description"], "Updated release")
        self.assertEqual(self.task_provider.dict_task_list, original_cache)

    def test_record_work_reports_confirmed_task_when_statistics_fail_before_replace(self) -> None:
        original_work_done = copy.deepcopy(self.statistics.workDone)
        original_fsync = os.fsync
        file_fsyncs = 0

        def fail_second_file_sync(fd: int) -> None:
            nonlocal file_fsyncs
            if stat.S_ISREG(os.fstat(fd).st_mode):
                file_fsyncs += 1
                if file_fsyncs == 2:
                    raise OSError("injected statistics file fsync failure")
            original_fsync(fd)

        with patch("src.AtomicFileStore.os.fsync", side_effect=fail_second_file_sync), self.assertRaises(
            OperationFailedError
        ) as caught:
            self.application.execute_operation(
                "record-work",
                OperationTarget("task", self.TASK_ID),
                {"duration": "1p", "now": TimePoint.now()},
            )

        self.assertEqual(caught.exception.effects_state, "partial")
        self.assertEqual(
            caught.exception.details.get("failed_resource"),
            "statistics",
            msg=f"{caught.exception.details!r}; cause={caught.exception.__cause__!r}",
        )
        self.assertEqual(caught.exception.details.get("saved_count"), "1")
        self.assertEqual(json.loads(caught.exception.details["saved_ids"]), [self.TASK_ID])
        stored_task = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(float(stored_task["investedEffort"]), 3.0)
        self.assertFalse(self.statistics_path.exists())
        self.assertEqual(self.statistics.workDone, original_work_done)

    def test_record_work_reports_unknown_statistics_after_replace_with_task_id_known(self) -> None:
        original_work_done = copy.deepcopy(self.statistics.workDone)
        original_fsync = os.fsync
        original_replace = os.replace
        statistics_replaced = False

        def mark_statistics_replace(source, destination):
            nonlocal statistics_replaced
            result = original_replace(source, destination)
            if Path(destination) == self.statistics_path:
                statistics_replaced = True
            return result

        def fail_statistics_directory_sync(fd: int) -> None:
            nonlocal statistics_replaced
            if statistics_replaced and stat.S_ISDIR(os.fstat(fd).st_mode):
                statistics_replaced = False
                raise OSError("injected statistics directory fsync failure")
            original_fsync(fd)

        with patch("src.AtomicFileStore.os.replace", side_effect=mark_statistics_replace), patch(
            "src.AtomicFileStore.os.fsync", side_effect=fail_statistics_directory_sync
        ), self.assertRaises(OperationFailedError) as caught:
            self.application.execute_operation(
                "record-work",
                OperationTarget("task", self.TASK_ID),
                {"duration": "1p", "now": TimePoint.now()},
            )

        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertEqual(
            caught.exception.details.get("failed_resource"),
            "statistics",
            msg=repr(caught.exception.details),
        )
        self.assertEqual(caught.exception.details.get("saved_count"), "1")
        self.assertEqual(json.loads(caught.exception.details["saved_ids"]), [self.TASK_ID])
        self.assertTrue(self.statistics_path.exists())
        self.assertEqual(self.statistics.workDone, original_work_done)

    def test_record_work_publishes_typed_statistics_log_only_after_commit(self) -> None:
        self.application.execute_operation(
            "record-work",
            OperationTarget("task", self.TASK_ID),
            {"duration": "1p", "now": TimePoint.now()},
        )

        log_entries = self.statistics.workDone["log"]
        self.assertIsInstance(log_entries, list)
        self.assertEqual(len(log_entries), 1)
        self.assertIsInstance(log_entries[0], WorkLogEntry)
        self.assertEqual(self.statistics.getWorkDoneLog(), log_entries)

    def test_confirmed_task_refresh_preserves_same_day_start_and_due_values(self) -> None:
        day = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        record = self._task_record()
        record["start"] = str(int((day + datetime.timedelta(hours=15)).timestamp() * 1000))
        record["due"] = str(int(day.timestamp() * 1000))
        self._write_tasks([record])

        original = self.application.read_task(self.TASK_ID)
        original_start = original.getStart().as_int()
        original_due = original.getDue().as_int()
        updated = self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        self.assertEqual(updated.getStart().as_int(), original_start)
        self.assertEqual(updated.getDue().as_int(), original_due)
        stored = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(int(stored["start"]), original_start)
        self.assertEqual(int(stored["due"]), original_due)

    def _new_obsidian_application(self, markdown_path: Path) -> tuple[ObsidianTaskProvider, TaskApplicationService]:
        markdown_path.write_text(
            "- [ ] Markdown release [track:: work:operations] "
            "[starts:: 2026-10-05T15:00] [due:: 2026-10-05] [severity:: 1] "
            "[remaining_cost:: 8] [invested:: 2] [calm:: false] [id:: markdown-1]\n",
            encoding="utf-8",
        )
        json_provider = ObsidianVaultTaskJsonProvider(
            self.file_broker,
            TaskDiscoveryPolicies("1", "1", "work", ["work", "home"]),
            auto_start=False,
            disableThreading=True,
        )
        provider = ObsidianTaskProvider(json_provider, self.file_broker, disableThreading=True)
        provider.start()
        manager = TelegramTaskListManager([], [], [], [], self.statistics)
        application = TaskApplicationService(
            provider,
            scheduling=None,
            statistics_service=self.statistics,
            task_list_manager=manager,
            categories=[{"prefix": "work"}, {"prefix": "home"}],
        )
        return provider, application

    def test_warm_markdown_reads_use_one_generation_and_local_save_publishes_before_return(self) -> None:
        markdown_path = self.vault_dir / "Operations.md"
        provider, _ = self._new_obsidian_application(markdown_path)
        initial = provider.getTaskListSnapshot()
        task = initial.tasks[0]
        task.setDescription("Saved Markdown release")
        status_before = provider.getRefreshStatus()

        with patch.object(self.file_broker, "getVaultFiles", wraps=self.file_broker.getVaultFiles) as inventory, patch.object(
            self.file_broker,
            "getVaultFileLines",
            wraps=self.file_broker.getVaultFileLines,
        ) as line_reads:
            provider.saveTask(task)
            resolved = provider.getTaskById("markdown-1")
            metadata = provider.getTaskMetadata(resolved)

        status_after = provider.getRefreshStatus()
        self.assertGreater(status_after["generation"], initial.generation)
        self.assertEqual(status_after["last_success"], status_before["last_success"])
        self.assertEqual(inventory.call_count, 0)
        self.assertEqual(line_reads.call_count, 0)
        self.assertEqual(resolved.getTaskText(), "Saved Markdown release")
        self.assertIn("Saved Markdown release", metadata)

    def test_mutation_read_uses_latest_target_fields_without_a_vault_rescan(self) -> None:
        markdown_path = self.vault_dir / "Operations.md"
        provider, _ = self._new_obsidian_application(markdown_path)
        provider.getTaskById("markdown-1")
        latest_due = "2026-11-02"
        external = markdown_path.read_text(encoding="utf-8").replace(
            "[invested:: 2]", "[invested:: 7]"
        ).replace("[due:: 2026-10-05]", f"[due:: {latest_due}]")
        markdown_path.write_text(external, encoding="utf-8")

        with patch.object(self.file_broker, "getVaultFiles", wraps=self.file_broker.getVaultFiles) as inventory:
            latest = provider.getTaskForMutation("markdown-1")
            self.assertEqual(latest.getInvestedEffort().as_pomodoros(), 7.0)
            self.assertEqual(latest.getDue(), TimePoint.from_string(latest_due))
            latest.setDescription("Latest fields preserved")
            provider.saveTask(latest)

        self.assertEqual(inventory.call_count, 0)
        stored = markdown_path.read_text(encoding="utf-8")
        self.assertIn("[invested:: 7]", stored)
        self.assertIn(f"[due:: {latest_due}]", stored)
        self.assertIn("Latest fields preserved", stored)

    def test_unknown_post_replace_markdown_write_invalidates_target_until_refresh(self) -> None:
        markdown_path = self.vault_dir / "Operations.md"
        provider, _ = self._new_obsidian_application(markdown_path)
        task = provider.getTaskById("markdown-1")
        task.setDescription("Uncertain but committed")
        original_replace = os.replace
        original_fsync = os.fsync
        replace_returned = False

        def mark_replace(source, destination):
            nonlocal replace_returned
            result = original_replace(source, destination)
            replace_returned = True
            return result

        def fail_directory_sync(fd: int) -> None:
            if replace_returned and stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected Markdown directory fsync failure")
            original_fsync(fd)

        with patch("src.AtomicFileStore.os.replace", side_effect=mark_replace), patch(
            "src.AtomicFileStore.os.fsync", side_effect=fail_directory_sync
        ), self.assertRaises(AtomicWriteError) as caught:
            provider.saveTask(task)

        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertTrue(provider.getRefreshStatus()["needs_refresh"])
        self.assertIn("Uncertain but committed", markdown_path.read_text(encoding="utf-8"))
        with self.assertRaises(SnapshotRefreshRequiredError):
            provider.getTaskById("markdown-1")

        provider.TaskJsonProvider.refresh()
        self.assertEqual(provider.getTaskById("markdown-1").getTaskText(), "Uncertain but committed")

    def test_midnight_target_patch_does_not_mark_other_files_reparsed(self) -> None:
        target_path = self.vault_dir / "target.md"
        other_path = self.vault_dir / "other.md"
        target_path.write_text(
            "- [ ] Target [track:: work:operations] [id:: target-id]\n",
            encoding="utf-8",
        )
        other_path.write_text(
            "- [ ] Other [track:: work:operations] [id:: other-id]\n",
            encoding="utf-8",
        )
        json_provider = ObsidianVaultTaskJsonProvider(
            self.file_broker,
            TaskDiscoveryPolicies("1", "1", "work", ["work", "home"]),
            auto_start=False,
            disableThreading=True,
        )
        provider = ObsidianTaskProvider(json_provider, self.file_broker, disableThreading=True)
        first_day = TimePoint.from_string("2026-10-01")
        next_day = TimePoint.from_string("2026-10-02")
        with patch("src.taskjsonproviders.ObsidianVaultTaskJsonProvider.TimePoint.today", return_value=first_day):
            provider.start()
            first_target = provider.getTaskById("target-id")
            first_other = provider.getTaskById("other-id")
            first_other_start = first_other.getStart().as_int()

        with patch("src.taskjsonproviders.ObsidianVaultTaskJsonProvider.TimePoint.today", return_value=next_day):
            first_target.setDescription("Edited after midnight")
            provider.saveTask(first_target)
            patched_status = provider.getRefreshStatus()
            stale_other = provider.getTaskById("other-id")
            json_provider.refresh()
            refreshed_other = provider.getTaskById("other-id")

        self.assertEqual(patched_status["local_day"], "2026-10-01")
        self.assertEqual(stale_other.getStart().as_int(), first_other_start)
        self.assertEqual(refreshed_other.getStart().as_int(), next_day.as_int())

    def test_discovery_keeps_first_confirmed_file_when_second_commit_fails(self) -> None:
        (self.vault_dir / "first.md").write_text(
            "---\nproject: open\ntrack: work:operations\n---\n# First\n",
            encoding="utf-8",
        )
        (self.vault_dir / "second.md").write_text(
            "---\nproject: open\ntrack: work:operations\n---\n# Second\n",
            encoding="utf-8",
        )
        json_provider = ObsidianVaultTaskJsonProvider(
            self.file_broker,
            TaskDiscoveryPolicies("1", "1", "work", ["work", "home"]),
            auto_start=False,
            disableThreading=True,
        )
        provider = ObsidianTaskProvider(json_provider, self.file_broker, disableThreading=True)
        provider.start()
        original_update = self.file_broker.updateVaultFileLines
        calls = 0

        def fail_second(registry, relative_path, updater):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second project write failure")
            return original_update(registry, relative_path, updater)

        with patch.object(self.file_broker, "updateVaultFileLines", side_effect=fail_second):
            with self.assertRaises(OperationExecutionError):
                json_provider.discover()

        published = json_provider.getJson()["tasks"]
        self.assertEqual(len(published), 1)
        persisted = [
            path.name
            for path in self.vault_dir.glob("*.md")
            if "Define next action" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(persisted), 1)
        self.assertEqual(published[0]["file"], persisted[0])

    def test_markdown_external_known_field_survives_recalculated_edit(self) -> None:
        markdown_path = self.vault_dir / "Operations.md"
        _, application = self._new_obsidian_application(markdown_path)
        original_stage = AtomicFileStore._stage
        injected = False

        def change_track_during_save(path: str, content: bytes, mode: int | None, validator) -> str:
            nonlocal injected
            temporary_path = original_stage(path, content, mode, validator)
            if Path(path) == markdown_path and not injected:
                injected = True
                markdown_path.write_text(
                    markdown_path.read_text(encoding="utf-8").replace(
                        "[track:: work:operations]",
                        "[track:: home:external]",
                    ),
                    encoding="utf-8",
                )
            return temporary_path

        with patch("src.AtomicFileStore.AtomicFileStore._stage", side_effect=change_track_during_save):
            updated = application.edit_task(
                "markdown-1", {"description": "Updated Markdown release"}
            )

        self.assertTrue(injected)
        final_markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("Updated Markdown release", final_markdown)
        self.assertIn("[track:: home:external]", final_markdown)
        self.assertEqual(updated.getContext(), "home:external")

    def test_markdown_pre_replace_failure_is_known_and_preserves_original_note(self) -> None:
        markdown_path = self.vault_dir / "Operations.md"
        provider, application = self._new_obsidian_application(markdown_path)
        original = markdown_path.read_bytes()

        with self._file_fsync_failure(), self.assertRaises(OperationFailedError) as caught:
            application.edit_task("markdown-1", {"description": "Updated Markdown release"})

        self.assertEqual(caught.exception.effects_state, "none")
        self.assertEqual(caught.exception.details.get("write_replaced"), "false")
        self.assertEqual(markdown_path.read_bytes(), original)
        self.assertEqual(provider.getTaskList()[0].getTaskText(), "Markdown release")

    def test_markdown_refresh_failure_after_confirmed_replace_is_unknown(self) -> None:
        markdown_path = self.vault_dir / "Operations.md"
        provider, application = self._new_obsidian_application(markdown_path)
        materialize = getattr(provider, "_ObsidianTaskProvider__materializeTaskFromLines")
        materializations = 0

        def fail_after_confirmed_update(file: str, lines: list[str], task_id: str):
            nonlocal materializations
            materializations += 1
            if materializations == 3:
                raise ValueError("injected confirmed Markdown refresh failure")
            return materialize(file, lines, task_id)

        with patch.object(
            provider,
            "_ObsidianTaskProvider__materializeTaskFromLines",
            side_effect=fail_after_confirmed_update,
        ), self.assertRaises(OperationFailedError) as caught:
            application.edit_task("markdown-1", {"description": "Updated Markdown release"})

        self.assertEqual(materializations, 3)
        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertEqual(caught.exception.details.get("uncertain_id"), "markdown-1")
        self.assertIn("Updated Markdown release", markdown_path.read_text(encoding="utf-8"))

    def test_interrupted_split_stops_after_first_confirmed_task_and_reports_its_id(self) -> None:
        scheduling = HeuristicScheduling(TimeAmount("5p"), self.task_provider)
        self.application._scheduling = scheduling
        original_fsync = os.fsync
        file_fsyncs = 0

        def fail_second_file_sync(fd: int) -> None:
            nonlocal file_fsyncs
            if stat.S_ISREG(os.fstat(fd).st_mode):
                file_fsyncs += 1
                if file_fsyncs == 2:
                    raise OSError("injected second task file fsync failure")
            original_fsync(fd)

        with patch("src.AtomicFileStore.os.fsync", side_effect=fail_second_file_sync), self.assertRaises(
            OperationFailedError
        ) as caught:
            self.application.execute_operation(
                "schedule-task",
                OperationTarget("task", self.TASK_ID),
                {"effort_per_day": "11p"},
            )

        self.assertEqual(caught.exception.effects_state, "partial")
        self.assertEqual(caught.exception.details.get("saved_count"), "1")
        self.assertEqual(json.loads(caught.exception.details["saved_ids"]), [self.TASK_ID])
        stored_tasks = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"]
        self.assertEqual(len(stored_tasks), 1)
        self.assertEqual(stored_tasks[0]["id"], self.TASK_ID)
        self.assertEqual(stored_tasks[0]["description"], "Plan release 1/3")
        self.assertEqual(list(self.data_dir.glob(".elrik-atomic-*.tmp")), [])

    def test_split_keeps_unknown_last_write_unknown_and_lists_prior_confirmed_id(self) -> None:
        self.application._scheduling = HeuristicScheduling(TimeAmount("5p"), self.task_provider)
        original_fsync = os.fsync
        original_replace = os.replace
        replacements = 0

        def count_replacements(source, destination):
            nonlocal replacements
            result = original_replace(source, destination)
            replacements += 1
            return result

        def fail_second_directory_sync(fd: int) -> None:
            if stat.S_ISDIR(os.fstat(fd).st_mode) and replacements == 2:
                raise OSError("injected uncertain second task replace")
            original_fsync(fd)

        with patch("src.AtomicFileStore.os.replace", side_effect=count_replacements), patch(
            "src.AtomicFileStore.os.fsync", side_effect=fail_second_directory_sync
        ), self.assertRaises(OperationFailedError) as caught:
            self.application.execute_operation(
                "schedule-task",
                OperationTarget("task", self.TASK_ID),
                {"effort_per_day": "11p"},
            )

        saved_ids = json.loads(caught.exception.details["saved_ids"])
        uncertain_id = caught.exception.details["uncertain_id"]
        stored_tasks = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"]
        self.assertEqual(caught.exception.effects_state, "unknown")
        self.assertEqual(caught.exception.details.get("saved_count"), "1")
        self.assertEqual(saved_ids, [self.TASK_ID])
        self.assertNotIn(uncertain_id, saved_ids)
        self.assertEqual(len(stored_tasks), 2)
        self.assertEqual(stored_tasks[1]["id"], uncertain_id)

    def test_external_edit_is_reloaded_before_save_and_unrelated_data_survives(self) -> None:
        original_save = self.task_provider.saveTask

        def edit_file_before_save(task) -> None:
            data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
            data["externalEdit"] = {"retain": True}
            data["tasks"][0]["context"] = "home:external"
            data["tasks"][0]["unknownTaskField"]["external"] = "kept"
            self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            original_save(task)

        with patch.object(self.task_provider, "saveTask", side_effect=edit_file_before_save):
            self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        stored = json.loads(self.tasks_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["externalEdit"], {"retain": True})
        self.assertEqual(stored["tasks"][0]["context"], "home:external")
        self.assertEqual(stored["tasks"][0]["unknownTaskField"], {"retain": True, "external": "kept"})
        self.assertEqual(stored["tasks"][0]["description"], "Updated release")

    def test_explicit_value_equal_to_baseline_overwrites_only_requested_external_field(self) -> None:
        original_stage = AtomicFileStore._stage
        injected = False

        def edit_during_save(path: str, content: bytes, mode: int | None, validator) -> str:
            nonlocal injected
            temporary_path = original_stage(path, content, mode, validator)
            if Path(path) == self.tasks_path and not injected:
                injected = True
                data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
                data["tasks"][0]["description"] = "External title"
                data["tasks"][0]["context"] = "home:external"
                self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return temporary_path

        with patch("src.AtomicFileStore.AtomicFileStore._stage", side_effect=edit_during_save):
            self.application.edit_task(self.TASK_ID, {"description": "Plan release"})

        self.assertTrue(injected)
        stored_task = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(stored_task["description"], "Plan release")
        self.assertEqual(stored_task["context"], "home:external")

    def test_external_change_during_preparation_recalculates_on_fresh_file(self) -> None:
        original_stage = AtomicFileStore._stage
        stage_count = 0

        def edit_after_stage(path: str, content: bytes, mode: int | None, validator) -> str:
            nonlocal stage_count
            temporary_path = original_stage(path, content, mode, validator)
            stage_count += 1
            if Path(path) == self.tasks_path and stage_count == 1:
                data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
                data["tasks"][0]["context"] = "home:changed-during-save"
                self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return temporary_path

        with patch("src.AtomicFileStore.AtomicFileStore._stage", side_effect=edit_after_stage):
            self.application.edit_task(self.TASK_ID, {"description": "Updated release"})

        stored_task = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertGreaterEqual(stage_count, 2)
        self.assertEqual(stored_task["context"], "home:changed-during-save")
        self.assertEqual(stored_task["description"], "Updated release")

    def test_invalid_external_model_change_blocks_recalculated_save_without_publication(self) -> None:
        original_stage = AtomicFileStore._stage
        original_cache = copy.deepcopy(self.task_provider.dict_task_list)
        external_bytes: list[bytes] = []
        injected = False

        def invalidate_during_save(path: str, content: bytes, mode: int | None, validator) -> str:
            nonlocal injected
            temporary_path = original_stage(path, content, mode, validator)
            if Path(path) == self.tasks_path and not injected:
                injected = True
                data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
                data["tasks"][0]["severity"] = "not-a-number"
                self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                external_bytes.append(self.tasks_path.read_bytes())
            return temporary_path

        with patch("src.AtomicFileStore.AtomicFileStore._stage", side_effect=invalidate_during_save), self.assertRaises(
            OperationFailedError
        ) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Must not overwrite invalid external data"})

        self.assertTrue(injected)
        self.assertEqual(caught.exception.effects_state, "none")
        self.assertEqual(self.tasks_path.read_bytes(), external_bytes[0])
        self.assertEqual(self.task_provider.dict_task_list, original_cache)

    def test_external_title_survives_effort_update(self) -> None:
        original_save = self.task_provider.saveTask

        def change_title_before_save(task) -> None:
            data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
            data["tasks"][0]["description"] = "Title from external editor"
            self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            original_save(task)

        with patch.object(self.task_provider, "saveTask", side_effect=change_title_before_save):
            self.application.execute_operation(
                "record-work",
                OperationTarget("task", self.TASK_ID),
                {"duration": "1p", "now": TimePoint.now()},
            )

        stored_task = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(stored_task["description"], "Title from external editor")
        self.assertEqual(float(stored_task["investedEffort"]), 3.0)

    def test_external_context_survives_snooze_update(self) -> None:
        original_save = self.task_provider.saveTask

        def change_context_before_save(task) -> None:
            data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
            data["tasks"][0]["context"] = "home:external"
            self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            original_save(task)

        with patch.object(self.task_provider, "saveTask", side_effect=change_context_before_save):
            self.application.execute_operation(
                "snooze-task",
                OperationTarget("task", self.TASK_ID),
                {"duration": "1h", "now": TimePoint.now()},
            )

        stored_task = json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"][0]
        self.assertEqual(stored_task["context"], "home:external")

    def test_task_removed_externally_before_save_is_not_recreated(self) -> None:
        original_stage = AtomicFileStore._stage
        removed = False

        def remove_during_save(path: str, content: bytes, mode: int | None, validator) -> str:
            nonlocal removed
            temporary_path = original_stage(path, content, mode, validator)
            if Path(path) == self.tasks_path and not removed:
                removed = True
                data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
                data["tasks"] = []
                self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return temporary_path

        with patch("src.AtomicFileStore.AtomicFileStore._stage", side_effect=remove_during_save), self.assertRaises(
            ResourceNotFoundError
        ) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Must not return"})

        self.assertTrue(removed)
        self.assertEqual(caught.exception.effects_state, "none")
        self.assertEqual(json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"], [])

    def test_ambiguous_external_identity_blocks_save(self) -> None:
        original_stage = AtomicFileStore._stage
        duplicated = False

        def duplicate_during_save(path: str, content: bytes, mode: int | None, validator) -> str:
            nonlocal duplicated
            temporary_path = original_stage(path, content, mode, validator)
            if Path(path) == self.tasks_path and not duplicated:
                duplicated = True
                data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
                data["tasks"].append(copy.deepcopy(data["tasks"][0]))
                self.tasks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return temporary_path

        with patch("src.AtomicFileStore.AtomicFileStore._stage", side_effect=duplicate_during_save), self.assertRaises(
            AmbiguousResourceError
        ) as caught:
            self.application.edit_task(self.TASK_ID, {"description": "Must not choose a copy"})

        self.assertTrue(duplicated)
        self.assertEqual(caught.exception.effects_state, "none")
        self.assertEqual(
            [task["description"] for task in json.loads(self.tasks_path.read_text(encoding="utf-8"))["tasks"]],
            ["Plan release", "Plan release"],
        )

    def test_replacement_preserves_permissions_and_readers_only_observe_complete_json(self) -> None:
        self.tasks_path.chmod(0o640)
        original_bytes = self.tasks_path.read_bytes()
        observed_before_replace: list[bytes] = []
        original_replace = os.replace

        def inspect_then_replace(source, destination):
            if Path(destination) == self.tasks_path:
                observed_before_replace.append(self.tasks_path.read_bytes())
            return original_replace(source, destination)

        with patch("src.AtomicFileStore.os.replace", side_effect=inspect_then_replace):
            self.application.edit_task(self.TASK_ID, {"description": "Atomic release"})

        final_bytes = self.tasks_path.read_bytes()
        self.assertEqual(observed_before_replace, [original_bytes])
        self.assertEqual(json.loads(observed_before_replace[0])["tasks"][0]["description"], "Plan release")
        self.assertEqual(json.loads(final_bytes)["tasks"][0]["description"], "Atomic release")
        self.assertEqual(stat.S_IMODE(self.tasks_path.stat().st_mode), 0o640)

    def test_restart_cleanup_removes_only_unpublished_atomic_temporaries(self) -> None:
        orphan = self.data_dir / f".elrik-atomic-{'a' * 32}.tmp"
        unrelated = self.data_dir / ".elrik-atomic-not-a-token.tmp"
        orphan.write_text("incomplete", encoding="utf-8")
        unrelated.write_text("keep", encoding="utf-8")
        original = self.tasks_path.read_bytes()

        removed = self.file_broker.cleanupAtomicTemps([str(self.data_dir)])

        self.assertEqual(removed, 1)
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(self.tasks_path.read_bytes(), original)


if __name__ == "__main__":
    import unittest

    unittest.main()
