import copy
import datetime
import os
import time
import unittest
from typing import List
from unittest.mock import MagicMock, patch

from src.AtomicFileStore import AtomicWriteError
from src.TelegramTaskListManager import TelegramTaskListManager
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.algorithms.ShortestJobAlgorithm import ShortestJobAlgorithm
from src.HeuristicScheduling import HeuristicScheduling
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import (
    AmbiguousResourceError,
    InvalidResourceDataError,
    OperationFailedError,
    ResourceNotFoundError,
    ResourceReadError,
    SnapshotRefreshRequiredError,
    ServiceNotReadyError,
    ValidationError,
)
from src.domain.models import AgendaQuery, OperationTarget, TaskView
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.heuristics.StartTimeHeuristic import StartTimeHeuristic
from src.taskmodels.TaskModel import TaskModel
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import (
    AmbiguousTaskIdentityError,
    InvalidTaskIdentityError,
    MissingTaskIdentityError,
)
from src.taskproviders.TaskProvider import TaskProvider
from src.Utils import WorkloadStats
from src.wrappers.TimeManagement import TimeAmount


class MemoryTaskProvider:
    """Small in-memory provider with the same explicit read/write boundary."""

    def __init__(self, tasks: list[TaskModel]):
        self.tasks = copy.deepcopy(tasks)
        self.saved: list[str] = []
        self.save_error: Exception | None = None
        self.fail_on_save_number: int | None = None
        self.discovery_calls = 0

    def getTaskList(self, include_completed: bool = False) -> List[TaskModel]:
        if getattr(self, "read_error", None) is not None:
            raise self.read_error
        tasks = copy.deepcopy(self.tasks)
        return tasks if include_completed else [task for task in tasks if task.getStatus() != "x"]

    def discoverTasks(self) -> List[TaskModel]:
        self.discovery_calls += 1
        return self.getTaskList()

    def saveTask(self, task: TaskModel) -> None:
        self.saved.append(task.getTaskUID())
        if self.save_error is not None:
            raise self.save_error
        if self.fail_on_save_number == len(self.saved):
            cause = OSError("injected persistence failure")
            raise AtomicWriteError("memory/tasks.json", "file_fsync", "none", False, cause)
        for index, current in enumerate(self.tasks):
            if current.getTaskUID() == task.getTaskUID():
                self.tasks[index] = copy.deepcopy(task)
                return
        self.tasks.append(copy.deepcopy(task))

    def createDefaultTask(self, description: str) -> TaskModel:
        task = make_task(len(self.tasks), description)
        self.tasks.append(copy.deepcopy(task))
        return task

    def getTaskMetadata(self, task: TaskModel) -> str:
        return "metadata"

    def discardPendingTaskReservations(self) -> None:
        pass


class MemoryTaskJsonProvider:
    def __init__(self, data: dict):
        self.data = copy.deepcopy(data)

    def getJson(self) -> dict:
        return copy.deepcopy(self.data)

    def saveJson(self, data: dict) -> None:
        self.data = copy.deepcopy(data)

    def updateJson(self, updater) -> dict:
        updated = updater(copy.deepcopy(self.data))
        self.data = copy.deepcopy(updated)
        return copy.deepcopy(self.data)

    def discover(self) -> dict:
        return self.getJson()


class PrefixFilter:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def filter(self, tasks: list[TaskModel]) -> list[TaskModel]:
        return [task for task in tasks if task.getContext().startswith(self.prefix)]

    def getDescription(self) -> str:
        return f"Tasks in {self.prefix}"


def make_task(
    index: int,
    description: str,
    context: str = "work",
    *,
    status: str = " ",
    raised: str | None = None,
    waited: str | None = None,
    due: int | None = None,
    start: int | None = None,
    cost: float = 8.0,
    invested: float = 2.0,
) -> TaskModel:
    return TaskModel(
        description,
        context,
        start if start is not None else 1_790_000_000_000 + index * 3_600_000,
        due if due is not None else 1_790_086_400_000 + index * 86_400_000,
        1.0,
        cost,
        invested,
        status,
        "False",
        "",
        index,
        raised,
        waited,
    )


class TaskApplicationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = MemoryTaskProvider(
            [
                make_task(0, "Release archived", "home", status="x"),
                make_task(1, "Release draft", "work", due=1_790_000_100_000),
                make_task(2, "Check deadline", "home", due=1_790_000_200_000),
                make_task(3, "Release waiting", "work", waited="review-ready"),
            ]
        )
        self.statistics = type("Statistics", (), {"doWork": lambda *args: None})()
        self.algorithms = [
            ("EDF", EdfAlgorithm()),
            ("Shortest Job", ShortestJobAlgorithm()),
        ]
        self.heuristics = [
            ("Remaining Effort(1)", RemainingEffortHeuristic(TimeAmount("2p"), 1.0)),
            ("Start Time Heuristic", StartTimeHeuristic()),
        ]
        self.filters = [
            ("All active task filter", PrefixFilter(""), True),
            ("Work", PrefixFilter("work"), False),
            ("Home", PrefixFilter("home"), False),
        ]
        self.manager = TelegramTaskListManager(
            self.provider.getTaskList(),
            self.algorithms,
            self.heuristics,
            self.filters,
            self.statistics,
        )
        self.application = TaskApplicationService(
            self.provider,
            scheduling=None,
            statistics_service=self.statistics,
            task_list_manager=self.manager,
            categories=[{"prefix": "work"}, {"prefix": "home"}],
        )

    def test_queries_are_isolated_and_keep_current_task_as_a_local_draft(self) -> None:
        selected_before = self.manager.filtered_task_list[0]
        self.manager.selected_task = selected_before
        self.manager.next_page()
        view_before = self.manager.current_view()
        first = self.application.query_tasks(
            TaskView(filters=("Work",), page=1, page_size=5, algorithm="EDF")
        )
        second = self.application.query_tasks(
            TaskView(filters=("Home",), page=1, page_size=5, algorithm="Shortest Job")
        )

        self.assertEqual([task.id for task in first.tasks], ["1"])
        self.assertEqual([task.id for task in second.tasks], ["2"])
        self.assertIn("Earliest Due Date", first.algorithm_desc)
        self.assertIn("Shortest Job First", second.algorithm_desc)
        self.assertIn("Earliest Due Date", first.algorithm_desc)
        self.assertEqual(self.manager.current_view(), view_before)
        self.assertIs(self.manager.selected_task, selected_before)
        self.assertEqual(self.manager.get_task_list_content().current_page, 2)
        self.assertEqual(self.provider.saved, [])

    def test_search_uses_all_noncompleted_tasks_and_skips_filters_and_strategies(self) -> None:
        self.provider.tasks.append(
            make_task(4, "Later release", "other", start=1_800_000_000_000)
        )
        content = self.application.query_tasks(
            TaskView(
                filters=("Work",),
                search=("release", "deadline"),
                algorithm="EDF",
            )
        )

        self.assertEqual(
            {task.description for task in content.tasks},
            {"Release draft", "Check deadline", "Release waiting", "Later release"},
        )
        self.assertEqual(content.algorithm_name, "None")
        self.assertEqual(content.sort_heuristic, "None")
        self.assertEqual(self.provider.saved, [])

    def test_empty_union_from_configured_catalog_is_empty(self) -> None:
        content = self.application.query_tasks(
            TaskView(filters=(), algorithm="", heuristic="")
        )

        self.assertEqual(content.tasks, [])
        self.assertEqual(content.total_tasks, 0)

    def test_statistics_and_count_reuse_one_algorithm_selected_population(self) -> None:
        class CountingFilter(PrefixFilter):
            def __init__(self) -> None:
                super().__init__("")
                self.calls = 0

            def filter(self, tasks: list[TaskModel]) -> list[TaskModel]:
                self.calls += 1
                return super().filter(tasks)

        active_filter = CountingFilter()
        self.application._task_list_manager._TelegramTaskListManager__filterList = [
            ("All active task filter", active_filter, True)
        ]
        stats = WorkloadStats(
            TimeAmount("0p"),
            TimeAmount("0p"),
            0.0,
            "",
            "",
            TimeAmount("0p"),
            {},
            [],
        )
        self.statistics.readWorkloadStats = MagicMock(return_value=stats)

        actual_stats, content = self.application.read_statistics_and_task_query(
            TaskView(filters=("All active task filter",), algorithm="", heuristic="")
        )

        self.assertIs(actual_stats, stats)
        self.assertEqual(active_filter.calls, 3)
        self.assertEqual(content.total_tasks, 2)
        self.statistics.readWorkloadStats.assert_called_once()
        self.assertEqual(len(self.statistics.readWorkloadStats.call_args.args[0]), 2)

    def test_task_reads_report_not_ready_instead_of_an_empty_vault(self) -> None:
        self.provider.isReady = lambda: False

        with self.assertRaises(ServiceNotReadyError):
            self.application.read_task_models()

    def test_query_ids_resolve_to_the_same_open_task_when_completed_tasks_precede_it(self) -> None:
        content = self.application.query_tasks(TaskView(filters=("Work",), algorithm="EDF"))

        resolved = self.application.read_task(content.tasks[0].id)
        details = self.application.read_task_information(content.tasks[0].id)

        self.assertEqual(resolved.getDescription(), "Release draft")
        self.assertEqual(resolved.getStatus(), " ")
        self.assertEqual(details.task.id, content.tasks[0].id)
        self.assertEqual(details.task.description, "Release draft")
        self.assertEqual(self.provider.saved, [])

    def test_edit_operation_validates_then_saves_one_combined_change(self) -> None:
        result = self.application.execute_operation(
            "edit-task",
            OperationTarget("task", "1"),
            {"changes": {"description": "Updated draft"}, "effort_delta": "1.5p"},
        )

        self.assertEqual(result.effects_state, "complete")
        self.assertEqual(result.value.getDescription(), "Updated draft")
        self.assertEqual(result.value.getInvestedEffort().as_pomodoros(), 3.52)
        self.assertEqual(result.value.getTotalCost().as_pomodoros(), 6.52)
        self.assertEqual(self.provider.saved, ["1"])

    def test_invalid_combined_edit_does_not_mutate_or_persist(self) -> None:
        with self.assertRaises(ValidationError):
            self.application.edit_task("1", {"context": "unknown", "severity": 4})

        self.assertEqual(self.provider.saved, [])
        self.assertEqual(self.application.read_task("1").getContext(), "work")

    def test_validation_preserves_negative_finite_severity_and_rejects_bad_duration_or_due_now(self) -> None:
        updated = self.application.edit_task("1", {"severity": -2.5})
        self.assertEqual(updated.getSeverity(), -2.5)
        self.assertEqual(self.provider.saved, ["1"])

        with self.assertRaises(ValidationError):
            self.application.edit_task("1", {"total_cost": "garbage"})
        with self.assertRaises(ValidationError):
            self.application.edit_task("1", {"total_cost": "2"})
        with self.assertRaises(ValidationError):
            self.application.execute_operation(
                "record-work", OperationTarget("task", "1"), {"duration": "2"}
            )
        with self.assertRaises(ValidationError):
            self.application.edit_task("1", {"due": "now"})
        with self.assertRaises(ValidationError):
            self.application.execute_operation(
                "edit-task", OperationTarget("task", "1"), {"unexpected": True}
            )

    def test_provider_read_failure_is_typed_instead_of_returning_empty_data(self) -> None:
        self.provider.read_error = OSError("read failed")

        with self.assertRaises(ResourceReadError):
            self.application.query_tasks(TaskView())
        with self.assertRaises(ResourceReadError):
            self.application.read_agenda(AgendaQuery())

    def test_invalidated_index_reads_return_refresh_conflict(self) -> None:
        def refresh_required(*_args, **_kwargs):
            error = RuntimeError("snapshot refresh required")
            error.code = "snapshot-refresh-required"
            raise error

        class InvalidatedSnapshot:
            getTaskById = staticmethod(refresh_required)

        with self.assertRaises(SnapshotRefreshRequiredError):
            self.application.read_task_from_snapshot("1", InvalidatedSnapshot())

        with patch.object(self.provider, "getTaskById", side_effect=refresh_required, create=True):
            with self.assertRaises(SnapshotRefreshRequiredError):
                self.application.read_task("1")

    def test_maintenance_runs_explicit_provider_discovery(self) -> None:
        result = self.application.maintain()

        self.assertEqual([task.getDescription() for task in result], [
            "Release draft", "Check deadline", "Release waiting"
        ])
        self.assertEqual(self.provider.discovery_calls, 1)
        self.assertEqual(self.provider.saved, [])

    def test_async_provider_discovers_after_readiness_instead_of_only_refreshing(self) -> None:
        class RefreshingProvider(MemoryTaskProvider):
            def __init__(self, tasks: list[TaskModel]) -> None:
                super().__init__(tasks)
                self.ready = True
                self.refresh_requests = 0

            def isReady(self) -> bool:
                return self.ready

            def requestRefresh(self) -> None:
                self.refresh_requests += 1

        provider = RefreshingProvider(self.provider.tasks)
        manager = TelegramTaskListManager(
            provider.getTaskList(),
            self.algorithms,
            self.heuristics,
            self.filters,
            self.statistics,
        )
        application = TaskApplicationService(
            provider,
            scheduling=None,
            statistics_service=self.statistics,
            task_list_manager=manager,
            categories=[{"prefix": "work"}, {"prefix": "home"}],
        )

        discovered = application.discover_initialize()

        self.assertEqual(provider.discovery_calls, 1)
        self.assertEqual(provider.refresh_requests, 0)
        self.assertEqual(len(discovered), 3)

        provider.ready = False
        with self.assertRaises(ServiceNotReadyError):
            application.discover_initialize()
        self.assertEqual(provider.refresh_requests, 1)

    def test_missing_and_ambiguous_ids_are_typed_errors_and_block_writes(self) -> None:
        with self.assertRaises(ResourceNotFoundError):
            self.application.read_task("missing")
        self.provider.tasks.append(copy.deepcopy(self.provider.tasks[1]))
        original = [task.getDescription() for task in self.provider.tasks]
        with self.assertRaises(AmbiguousResourceError):
            self.application.read_task("1")
        with self.assertRaises(AmbiguousResourceError):
            self.application.edit_task("1", {"description": "Must not be saved"})
        self.assertEqual(self.provider.saved, [])
        self.assertEqual([task.getDescription() for task in self.provider.tasks], original)

    def test_provider_identity_data_errors_keep_their_domain_type(self) -> None:
        self.provider.read_error = InvalidTaskIdentityError("empty id")
        with self.assertRaises(InvalidResourceDataError):
            self.application.read_task("1")

        self.provider.read_error = None
        self.provider.save_error = InvalidTaskIdentityError("invalid declared id")
        with self.assertRaises(InvalidResourceDataError):
            self.application.edit_task("1", {"description": "Updated"})

        self.provider.save_error = AmbiguousTaskIdentityError("duplicate id")
        with self.assertRaises(AmbiguousResourceError):
            self.application.edit_task("1", {"description": "Updated"})

        self.provider.save_error = MissingTaskIdentityError("id no longer exists")
        with self.assertRaises(ResourceNotFoundError):
            self.application.edit_task("1", {"description": "Updated"})

    def test_complete_operation_reports_partial_effects_after_a_later_save_fails(self) -> None:
        self.provider.tasks = [
            make_task(0, "Release event", raised="review-ready"),
            make_task(1, "First waiter", waited="review-ready"),
            make_task(2, "Second waiter", waited="review-ready"),
        ]
        self.provider.fail_on_save_number = 2

        with self.assertRaises(OperationFailedError) as caught:
            self.application.execute_operation(
                "complete-task", OperationTarget("task", "0"), {}
            )

        self.assertEqual(caught.exception.effects_state, "partial")
        self.assertEqual(self.provider.saved, ["1", "2"])
        self.assertEqual(self.provider.tasks[1].getEventWaited(), None)
        self.assertEqual(self.provider.tasks[2].getEventWaited(), "review-ready")
        self.assertEqual(self.provider.tasks[0].getStatus(), " ")

    def test_complete_and_raise_event_release_exact_waiters_including_completed(self) -> None:
        self.provider.tasks = [
            make_task(0, "Raise event", raised="same-event"),
            make_task(1, "Open waiter", waited="same-event"),
            make_task(2, "Completed waiter", status="x", waited="same-event"),
            make_task(3, "Other waiter", waited="different-event"),
        ]

        result = self.application.execute_operation(
            "raise-event", OperationTarget("event", "same-event"), {}
        )

        self.assertEqual(result.affected_ids, ("1", "2"))
        self.assertIsNone(self.provider.tasks[1].getEventWaited())
        self.assertIsNone(self.provider.tasks[2].getEventWaited())
        self.assertEqual(self.provider.tasks[3].getEventWaited(), "different-event")

    def test_completing_event_raiser_releases_completed_waiters_too(self) -> None:
        self.provider.tasks = [
            make_task(0, "Raise event", raised="same-event"),
            make_task(1, "Open waiter", waited="same-event"),
            make_task(2, "Completed waiter", status="x", waited="same-event"),
        ]

        result = self.application.execute_operation(
            "complete-task", OperationTarget("task", "0"), {}
        )

        self.assertEqual(result.affected_ids, ("1", "2", "0"))
        self.assertIsNone(self.provider.tasks[1].getEventWaited())
        self.assertIsNone(self.provider.tasks[2].getEventWaited())
        self.assertEqual(self.provider.tasks[0].getStatus(), "x")

    def test_real_schedule_split_reserves_distinct_ids_until_saved(self) -> None:
        json_provider = MemoryTaskJsonProvider({
            "tasks": [{
                "description": "Split this",
                "context": "work",
                "start": "1790000000000",
                "due": "1790086400000",
                "severity": "1",
                "totalCost": "10",
                "investedEffort": "0",
                "status": " ",
                "calm": "False",
                "project": "",
            }],
        })
        file_broker = MagicMock()
        file_broker.getFilePath.return_value = "/configured/tasks.json"
        provider = TaskProvider(json_provider, file_broker, disableThreading=True)
        original_id = provider.getTaskList()[0].getTaskUID()
        manager = TelegramTaskListManager([], [], [], [], self.statistics)
        application = TaskApplicationService(
            provider,
            HeuristicScheduling(TimeAmount("5p"), provider),
            self.statistics,
            manager,
            [{"prefix": "work"}],
        )

        result = application.execute_operation(
            "schedule-task",
            OperationTarget("task", original_id),
            {"effort_per_day": "11p"},
        )

        self.assertEqual(len(result.value), 3)
        stored_ids = tuple(task.get("id") for task in json_provider.getJson()["tasks"])
        self.assertEqual(len(set(stored_ids)), 3)
        self.assertEqual(result.affected_ids, stored_ids)
        persisted = json_provider.getJson()["tasks"]
        self.assertEqual(len(persisted), 3)
        self.assertEqual([task["description"] for task in persisted], [
            "Split this 1/3", "Split this 2/3", "Split this 3/3"
        ])
        self.assertEqual([task.getTaskUID() for task in provider.getTaskList()], list(stored_ids))
        self.assertEqual(stored_ids[0], original_id)

    def test_empty_schedule_discards_pending_id_reservations(self) -> None:
        json_provider = MemoryTaskJsonProvider({
            "tasks": [{
                "description": "Split this",
                "context": "work",
                "start": "1790000000000",
                "due": "1790086400000",
                "severity": "1",
                "totalCost": "10",
                "investedEffort": "0",
                "status": " ",
                "calm": "False",
                "project": "",
            }],
        })
        file_broker = MagicMock()
        file_broker.getFilePath.return_value = "/configured/tasks.json"
        provider = TaskProvider(json_provider, file_broker, disableThreading=True)
        original_id = provider.getTaskList()[0].getTaskUID()
        manager = TelegramTaskListManager([], [], [], [], self.statistics)

        class EmptyScheduler:
            def schedule(self, task, effort):
                provider.createDefaultTask("Abandoned part")
                return []

        application = TaskApplicationService(
            provider, EmptyScheduler(), self.statistics, manager, [{"prefix": "work"}]
        )
        with self.assertRaises(OperationFailedError):
            application.execute_operation(
                "schedule-task", OperationTarget("task", original_id), {}
            )

        self.assertEqual(
            provider.createDefaultTask("Next part").getTaskUID(),
            fallback_task_id("Next part", "/configured/tasks.json", 1),
        )

    def test_schedule_exception_discards_pending_id_reservations(self) -> None:
        json_provider = MemoryTaskJsonProvider({
            "tasks": [{
                "description": "Split this",
                "context": "work",
                "start": "1790000000000",
                "due": "1790086400000",
                "severity": "1",
                "totalCost": "10",
                "investedEffort": "0",
                "status": " ",
                "calm": "False",
                "project": "",
            }],
        })
        file_broker = MagicMock()
        file_broker.getFilePath.return_value = "/configured/tasks.json"
        provider = TaskProvider(json_provider, file_broker, disableThreading=True)
        original_id = provider.getTaskList()[0].getTaskUID()
        manager = TelegramTaskListManager([], [], [], [], self.statistics)

        class FailingScheduler:
            def schedule(self, task, effort):
                provider.createDefaultTask("Abandoned part")
                raise ValueError("scheduler failed")

        application = TaskApplicationService(
            provider, FailingScheduler(), self.statistics, manager, [{"prefix": "work"}]
        )
        with self.assertRaises(OperationFailedError):
            application.execute_operation(
                "schedule-task", OperationTarget("task", original_id), {}
            )

        self.assertEqual(
            provider.createDefaultTask("Next part").getTaskUID(),
            fallback_task_id("Next part", "/configured/tasks.json", 1),
        )

    def test_offset_iso_times_keep_the_instant_across_dst_and_relative_edits(self) -> None:
        previous_timezone = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            task = make_task(10, "DST task")
            before_fallback = self.application._parse_time(
                task,
                "start",
                "2026-11-01T01:30:00-04:00",
            )
            after_fallback = self.application._parse_time(
                task,
                "start",
                "2026-11-01T01:30:00-05:00",
            )
            utc_after_fallback = self.application._parse_time(
                task,
                "start",
                "2026-11-01T06:30:00Z",
            )

            self.assertIsNone(before_fallback.datetime_representation.tzinfo)
            self.assertIsNone(after_fallback.datetime_representation.tzinfo)
            self.assertEqual(after_fallback.as_int() - before_fallback.as_int(), 60 * 60 * 1000)
            self.assertEqual(utc_after_fallback.as_int(), after_fallback.as_int())

            local_due = self.application._parse_time(
                task,
                "due",
                "2026-11-01T01:30",
            )
            self.assertEqual(
                local_due.datetime_representation,
                datetime.datetime(2026, 11, 1, 1, 30),
            )

            task.setStart(after_fallback)
            relative = self.application._parse_time(task, "start", "+5m")
            self.assertIsNone(relative.datetime_representation.tzinfo)
            self.assertEqual(relative.as_int() - after_fallback.as_int(), 5 * 60 * 1000)
        finally:
            if previous_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_timezone
            time.tzset()


if __name__ == "__main__":
    unittest.main()
