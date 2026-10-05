"""Application and project mutation contracts across the shared FIFO."""

from __future__ import annotations

import asyncio
import copy
import threading
import unittest
from uuid import uuid4

from src.JsonProjectManager import JsonProjectManager
from src.MutationCoordinator import MutationCoordinator
from src.ProjectManager import ObsidianProjectManager
from src.TelegramTaskListManager import TelegramTaskListManager
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import (
    InvalidResourceDataError,
    OperationConflictError,
    OperationResultUnavailableError,
    ValidationError,
)
from src.domain.models import OperationTarget, ProjectMutationResult
from tests.TaskApplicationService_test import MemoryTaskProvider, make_task


class RecordingStatistics:
    def __init__(self) -> None:
        self.work: list[tuple[object, ...]] = []

    def doWork(self, *args: object) -> None:
        self.work.append(args)


class MemoryProjectJsonProvider:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = copy.deepcopy(data)
        self.update_calls = 0
        self.writes = 0

    def updateJson(self, updater):
        self.update_calls += 1
        updated = updater(copy.deepcopy(self.data))
        self.data = copy.deepcopy(updated)
        self.writes += 1
        return copy.deepcopy(self.data)


class MemoryMarkdownTaskProvider:
    def __init__(self, projects: list[dict[str, str]]) -> None:
        self.projects = copy.deepcopy(projects)

    def getTaskListAttribute(self, attribute: str) -> list[dict[str, str]]:
        return copy.deepcopy(self.projects if attribute == "projects" else [])


class MemoryVaultFileBroker:
    def __init__(self, lines_by_path: dict[str, list[str]]) -> None:
        self.lines_by_path = copy.deepcopy(lines_by_path)
        self.writes = 0

    def updateVaultFileLines(self, registry, path: str, updater):
        updated = updater(copy.deepcopy(self.lines_by_path[path]))
        self.lines_by_path[path] = copy.deepcopy(updated)
        self.writes += 1
        return copy.deepcopy(updated)

    def createVaultFileLinesIfAbsent(self, registry, path: str, lines: list[str]) -> bool:
        if path in self.lines_by_path:
            return False
        self.lines_by_path[path] = copy.deepcopy(lines)
        self.writes += 1
        return True


class DomainMutationAdmissionTest(unittest.TestCase):
    def _coordinator(self) -> MutationCoordinator:
        coordinator = MutationCoordinator()
        self.addCleanup(coordinator.close)
        return coordinator

    @staticmethod
    def _service(
        provider: MemoryTaskProvider,
        coordinator: MutationCoordinator,
        statistics: RecordingStatistics,
        project_manager=None,
    ) -> TaskApplicationService:
        return TaskApplicationService(
            provider,
            scheduling=None,
            statistics_service=statistics,
            task_list_manager=TelegramTaskListManager([], [], [], [], statistics),
            categories=[{"prefix": "work"}],
            project_manager=project_manager,
            mutation_coordinator=coordinator,
        )

    def test_same_uuid_reuses_outcome_and_rejects_a_different_intent(self) -> None:
        coordinator = self._coordinator()
        provider = MemoryTaskProvider([make_task(1, "Draft")])
        stats = RecordingStatistics()
        application = self._service(provider, coordinator, stats)
        operation_id = uuid4()
        target = OperationTarget("task", "1")

        first = application.submit_operation(
            operation_id,
            "edit-task",
            target,
            {"changes": {"description": "Reviewed draft"}},
        )
        duplicate = application.submit_operation(
            operation_id,
            "edit-task",
            target,
            {"changes": {"description": "Reviewed draft"}},
        )

        self.assertEqual(first.value.getDescription(), "Reviewed draft")
        self.assertEqual(duplicate.value.getDescription(), "Reviewed draft")
        self.assertEqual(provider.saved, ["1"])
        self.assertEqual(application.get_receipt(operation_id).status, "succeeded")
        with self.assertRaises(OperationConflictError):
            application.submit_operation(
                operation_id,
                "edit-task",
                target,
                {"changes": {"description": "Different draft"}},
            )

    def test_invalid_structure_is_rejected_before_reads_or_admission(self) -> None:
        coordinator = self._coordinator()
        provider = MemoryTaskProvider([make_task(1, "Draft")])
        read_attempts: list[str] = []

        def unexpected_read(include_completed: bool = False):
            read_attempts.append("read")
            raise AssertionError("invalid input must be rejected before reading task state")

        provider.getTaskList = unexpected_read
        application = self._service(provider, coordinator, RecordingStatistics())
        operation_id = uuid4()

        with self.assertRaises(ValidationError):
            application.submit_operation(
                operation_id,
                "edit-task",
                OperationTarget("task", "1"),
                {"changes": {"unknown_field": True}},
            )

        self.assertEqual(read_attempts, [])
        with self.assertRaises(OperationResultUnavailableError):
            application.get_receipt(operation_id)

    def test_later_queued_work_calculates_from_the_preceding_saved_state(self) -> None:
        coordinator = self._coordinator()
        task = make_task(1, "Work item", cost=8.0, invested=2.0)
        provider = MemoryTaskProvider([task])
        stats = RecordingStatistics()
        application = self._service(provider, coordinator, stats)
        target = OperationTarget("task", "1")
        first_id, second_id = uuid4(), uuid4()
        blocker_started = threading.Event()
        release_blocker = threading.Event()

        def block_worker() -> None:
            blocker_started.set()
            if not release_blocker.wait(2):
                raise TimeoutError("test did not release the coordinator")

        blocker = threading.Thread(target=lambda: coordinator.run_job(block_worker))
        blocker.start()
        self.assertTrue(blocker_started.wait(2))

        async def submit_queued_work():
            first = asyncio.create_task(
                application.submit_operation_async(
                    first_id, "record-work", target, {"duration": "1p"}
                )
            )
            second = asyncio.create_task(
                application.submit_operation_async(
                    second_id, "record-work", target, {"duration": "1p"}
                )
            )
            await asyncio.sleep(0)
            self.assertEqual(coordinator.get_receipt(first_id).status, "pending")
            self.assertEqual(coordinator.get_receipt(second_id).status, "pending")
            release_blocker.set()
            return await asyncio.gather(first, second)

        try:
            results = asyncio.run(submit_queued_work())
        finally:
            release_blocker.set()
            blocker.join(2)

        self.assertFalse(blocker.is_alive())
        self.assertEqual(len(results), 2)
        saved = provider.getTaskList()[0]
        self.assertEqual(saved.getInvestedEffort().as_pomodoros(), 4.0)
        self.assertEqual(saved.getTotalCost().as_pomodoros(), 6.0)
        self.assertEqual(provider.saved, ["1", "1"])
        self.assertEqual(len(stats.work), 2)

    def test_combined_effort_edit_saves_once_and_record_work_persists_statistics(self) -> None:
        coordinator = self._coordinator()
        provider = MemoryTaskProvider([make_task(1, "Draft", cost=8.0, invested=2.0)])
        stats = RecordingStatistics()
        application = self._service(provider, coordinator, stats)
        target = OperationTarget("task", "1")

        application.submit_operation(
            uuid4(),
            "edit-task",
            target,
            {"changes": {"description": "Final draft"}, "effort_delta": "1.5p"},
        )
        self.assertEqual(provider.saved, ["1"])

        application.submit_operation(
            uuid4(), "record-work", target, {"duration": "1p"}
        )

        self.assertEqual(provider.saved, ["1", "1"])
        self.assertEqual(len(stats.work), 1)
        saved = provider.getTaskList()[0]
        self.assertEqual(saved.getDescription(), "Final draft")
        self.assertEqual(saved.getInvestedEffort().as_pomodoros(), 4.52)
        self.assertEqual(saved.getTotalCost().as_pomodoros(), 5.52)

    def test_json_project_operations_return_data_and_reject_invalid_records_before_write(self) -> None:
        coordinator = self._coordinator()
        provider = MemoryTaskProvider([])
        stats = RecordingStatistics()
        projects = MemoryProjectJsonProvider({"projects": []})
        manager = JsonProjectManager(projects, mutation_coordinator=coordinator)
        application = self._service(provider, coordinator, stats, manager)

        opened = application.submit_operation(
            uuid4(),
            "open-project",
            OperationTarget("project", "New project"),
            {"description": "Initial description"},
        )
        self.assertIsInstance(opened.value, ProjectMutationResult)
        self.assertTrue(opened.value.created)
        self.assertEqual(opened.value.description, "Initial description")

        application.submit_operation(
            uuid4(),
            "edit-project-content",
            OperationTarget("project", "New project"),
            {"description": "Revised description"},
        )
        held = application.submit_operation(
            uuid4(), "hold-project", OperationTarget("project", "New project"), {}
        )
        self.assertEqual(held.value.status, "on-hold")
        self.assertEqual(projects.writes, 3)

        invalid_projects = MemoryProjectJsonProvider({
            "projects": [{"name": "Bad project", "description": 7, "status": "open"}]
        })
        invalid_manager = JsonProjectManager(invalid_projects, mutation_coordinator=coordinator)
        invalid_application = self._service(provider, coordinator, stats, invalid_manager)
        with self.assertRaises(InvalidResourceDataError):
            invalid_application.submit_operation(
                uuid4(), "close-project", OperationTarget("project", "Bad project"), {}
            )
        self.assertEqual(invalid_projects.writes, 0)

    def test_markdown_project_edits_return_committed_content_and_validate_before_write(self) -> None:
        coordinator = self._coordinator()
        provider = MemoryTaskProvider([])
        stats = RecordingStatistics()
        project_provider = MemoryMarkdownTaskProvider([
            {"name": "Project", "status": "open", "path": "project.md"}
        ])
        broker = MemoryVaultFileBroker({
            "project.md": ["---\n", "project: open\n", "---\n", "# Project\n", "Draft\n"]
        })
        manager = ObsidianProjectManager(project_provider, broker, mutation_coordinator=coordinator)
        application = self._service(provider, coordinator, stats, manager)

        edited = application.submit_operation(
            uuid4(),
            "edit-project-content",
            OperationTarget("project", "Project"),
            {"action": "replace", "line": 5, "content": "Reviewed"},
        )
        self.assertIsInstance(edited.value, ProjectMutationResult)
        self.assertEqual(edited.value.status, "open")
        self.assertIn("Reviewed\n", edited.value.content or "")

        invalid_broker = MemoryVaultFileBroker({"project.md": ["not project frontmatter\n"]})
        invalid_manager = ObsidianProjectManager(
            project_provider,
            invalid_broker,
            mutation_coordinator=coordinator,
        )
        invalid_application = self._service(provider, coordinator, stats, invalid_manager)
        with self.assertRaises(InvalidResourceDataError):
            invalid_application.submit_operation(
                uuid4(), "close-project", OperationTarget("project", "Project"), {}
            )
        self.assertEqual(invalid_broker.writes, 0)


if __name__ == "__main__":
    unittest.main()
