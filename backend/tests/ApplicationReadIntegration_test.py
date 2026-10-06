"""Integration checks for read-only application queries."""

import datetime
import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from unittest import TestCase
from unittest.mock import patch

from src.FileBroker import FileBroker
from src.HeuristicScheduling import HeuristicScheduling
from src.MutationCoordinator import MutationCoordinator
from src.StatisticsService import StatisticsService
from src.TelegramTaskListManager import TelegramTaskListManager
from src.Utils import TaskDiscoveryPolicies
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.algorithms.GtdAlgorithm import GtdAlgorithm
from src.algorithms.ShortestJobAlgorithm import ShortestJobAlgorithm
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import AmbiguousResourceError, InvalidResourceDataError, ResourceNotFoundError
from src.domain.models import AgendaQuery, OperationTarget, TaskView
from src.filters.ActiveTaskFilter import ActiveTaskFilter, InactiveTaskFilter
from src.filters.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.filters.WorkloadAbleFilter import WorkloadAbleFilter
from src.heuristics.CfdHeuristic import CfdHeuristic
from src.heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.heuristics.SlackHeuristic import SlackHeuristic
from src.heuristics.StartTimeHeuristic import StartTimeHeuristic
from src.heuristics.WorkloadHeuristic import WorkloadHeuristic
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.taskproviders.TaskProvider import TaskProvider
from src.wrappers.TimeManagement import TimeAmount, TimePoint
from src.api.ApiResources import ApiResources


class ApplicationReadIntegrationTest(TestCase):
    """Exercise real providers, view managers, strategies, and statistics."""

    FIXED_NOW = TimePoint(datetime.datetime(2026, 10, 4, 12, 0))

    @contextmanager
    def _fixed_clock(self) -> Iterator[None]:
        fixed_today = self.FIXED_NOW.strip_time()
        fixed_tomorrow = fixed_today + TimeAmount("1d")
        with patch.object(TimePoint, "now", return_value=self.FIXED_NOW), patch.object(
            TimePoint, "today", return_value=fixed_today
        ), patch.object(TimePoint, "tomorrow", return_value=fixed_tomorrow):
            yield

    @staticmethod
    def _snapshot(directory: Path) -> dict[str, bytes]:
        if not directory.exists():
            return {}
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }

    @staticmethod
    def _base_task(
        *,
        description: str,
        context: str,
        start: int,
        due: int,
        status: str = " ",
        project: str = "",
        waited: str | None = None,
        unknown: object | None = None,
    ) -> dict[str, object]:
        task: dict[str, object] = {
            "description": description,
            "context": context,
            "start": start,
            "due": due,
            "severity": 1.0,
            "totalCost": 8.0,
            "investedEffort": 2.0,
            "status": status,
            "calm": "False",
            "project": project,
            "raised": None,
            "waited": waited,
        }
        if unknown is not None:
            task["unknownTaskField"] = unknown
        return task

    def _create_query_stack(self, file_broker: FileBroker, task_provider, scheduling: Any | None = None):
        categories = [
            {"prefix": "alert", "description": "Alert"},
            {"prefix": "work", "description": "Work"},
            {"prefix": "home", "description": "Home"},
            {"prefix": "inbox", "description": "Inbox"},
        ]
        dedication = TimeAmount("2p")
        active_filter = ActiveTaskFilter()
        category_filters = [
            (
                category["description"],
                ContextPrefixTaskFilter(active_filter, category["prefix"]),
                False,
            )
            for category in categories
        ]
        filters = [
            ("All active task filter", active_filter, True),
            ("All inactive task filter", InactiveTaskFilter(), False),
            *category_filters,
        ]

        remaining_effort = RemainingEffortHeuristic(dedication, 1.0)
        slack = SlackHeuristic(dedication)
        cfd = CfdHeuristic(dedication)
        heuristics = [
            ("Remaining Effort(1)", remaining_effort),
            ("Remaining Time(100)", DaysToThresholdHeuristic(dedication, 100.0)),
            ("Remaining Time(1)", DaysToThresholdHeuristic(dedication, 1.0)),
            ("Slack Heuristic", slack),
            ("Start Time Heuristic", StartTimeHeuristic()),
            ("CFD Heuristic", cfd),
            ("Workload Heuristic", WorkloadHeuristic()),
        ]
        statistics = StatisticsService(
            file_broker,
            WorkloadAbleFilter(active_filter),
            remaining_effort,
            slack,
        )
        ordered_categories = [
            (category["description"], filterr, False)
            for category, (_, filterr, _) in zip(categories, category_filters)
        ]
        ordered_heuristics = [
            (SlackHeuristic(dedication, 1), 100.0),
            (SlackHeuristic(dedication), 10.0),
            (SlackHeuristic(dedication), 5.0),
        ]
        default_heuristic = (SlackHeuristic(dedication), 1.0)
        algorithms = [
            (
                "GTD Algorithm",
                GtdAlgorithm(
                    ordered_categories,
                    ordered_heuristics,
                    default_heuristic,
                    statistics,
                    cfd,
                ),
            ),
            ("EDF Algorithm", EdfAlgorithm()),
            ("Shortest Job Algorithm", ShortestJobAlgorithm()),
        ]

        channel_manager = TelegramTaskListManager(
            task_provider.getTaskList(),
            algorithms,
            heuristics,
            filters,
            statistics,
        )
        application = TaskApplicationService(
            task_provider,
            scheduling=scheduling,
            statistics_service=statistics,
            task_list_manager=channel_manager,
            categories=categories,
        )
        return application, channel_manager, statistics, algorithms

    def _write_json_fixture(self, path: Path) -> None:
        start_past = (self.FIXED_NOW + TimeAmount("-30d")).as_int()
        due_past = (self.FIXED_NOW + TimeAmount("-1d")).as_int()
        due_future = (self.FIXED_NOW + TimeAmount("3650d")).as_int()
        start_future = (self.FIXED_NOW + TimeAmount("1d")).as_int()
        tasks = [
            self._base_task(
                description="Completed release archival task",
                context="work:release",
                start=start_past,
                due=due_past,
                status="x",
                project="Empty open project",
                unknown={"preserve": True},
            ),
            self._base_task(
                description="Review release draft",
                context="work:writing",
                start=start_past,
                due=due_past,
                unknown={"source": "json"},
            ),
            self._base_task(
                description="Prepare home office",
                context="home:setup",
                start=start_past,
                due=due_future,
            ),
            self._base_task(
                description="Wait for reviewer",
                context="work:review",
                start=start_past,
                due=due_future,
                waited="review-ready",
            ),
            self._base_task(
                description="Plan a future task",
                context="work:planning",
                start=start_future,
                due=due_future,
            ),
        ]
        path.write_text(
            json.dumps(
                {
                    "unknownTopLevel": {"preserve": "custom-value"},
                    "tasks": tasks,
                    "projects": [
                        {
                            "name": "Empty open project",
                            "description": "Has only a completed task.",
                            "status": "open",
                            "unknownProjectField": "preserve",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_markdown_fixture(self, vault: Path) -> None:
        start = (self.FIXED_NOW + TimeAmount("-30d")).strip_time()
        due_past = (self.FIXED_NOW + TimeAmount("-1d")).strip_time()
        due_future = (self.FIXED_NOW + TimeAmount("3650d")).strip_time()
        start_text = str(start)
        due_past_text = str(due_past)
        due_future_text = str(due_future)
        (vault / "Atlas.md").write_text(
            "---\n"
            "project: open\n"
            "starts: 2020-01-01\n"
            "due: 2099-01-01\n"
            "severity: 1\n"
            "remaining_cost: 8\n"
            "invested: 2\n"
            "track: work\n"
            "calm: false\n"
            "unknown_header: preserve\n"
            "---\n"
            "# Atlas\n"
            f"- [ ] Review release draft [track::work:writing] [starts::{start_text}] "
            f"[due::{due_past_text}] [severity::1] [remaining_cost::8] [invested::2] "
            "[calm::false] [raised::review-ready] [custom::preserve]\n"
            f"- [ ] Wait for reviewer [track::work:review] [starts::{start_text}] "
            f"[due::{due_future_text}] [severity::1] [remaining_cost::5] [invested::0] "
            "[calm::false] [waited::review-ready]\n"
            f"- [x] Completed launch checklist [track::work:release] [starts::{start_text}] "
            f"[due::{due_future_text}] [severity::1] [remaining_cost::2] [invested::2] "
            "[calm::false] [custom::completed]\n",
            encoding="utf-8",
        )
        (vault / "EmptyOpen.md").write_text(
            "---\n"
            "project: open\n"
            "unknown_header: retain-empty\n"
            "---\n"
            "# Empty Open\n"
            f"- [x] Completed action only [track::work:ops] [starts::{start_text}] "
            f"[due::{due_future_text}] [severity::1] [remaining_cost::1] [invested::1] "
            "[calm::false] [custom::retain]\n",
            encoding="utf-8",
        )

    def test_json_queries_preserve_files_views_and_direct_target(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            vault = root / "vault"
            vault.mkdir()
            tasks_path = data / "tasks.json"
            statistics_path = data / "statistics.json"
            self._write_json_fixture(tasks_path)

            file_broker = FileBroker(str(data), str(root / "appdata"), str(vault))
            json_provider = TaskJsonProvider(file_broker)
            task_provider = TaskProvider(json_provider, file_broker, disableThreading=True)
            application, channel_manager, statistics, algorithms = self._create_query_stack(
                file_broker,
                task_provider,
            )
            statistics.initialize()
            original_files = self._snapshot(data)
            original_view = channel_manager.current_view()
            original_selection = task_provider.getTaskList()[0]
            channel_manager.selected_task = original_selection
            channel_manager.select_algorithm("algorithm_2")
            channel_manager.select_heuristic("heuristic_5")
            channel_manager.select_filter("filter_3")
            channel_manager.next_page()
            channel_view_before_reads = channel_manager.current_view()
            selected_before_reads = channel_manager.selected_task
            algorithm_state_before_reads = [
                (getattr(algorithm, "description", None), getattr(algorithm, "category", None))
                for _, algorithm in algorithms
            ]
            catalogs_before_reads = (
                channel_manager.get_algorithm_list(),
                channel_manager.get_heuristic_list(),
                channel_manager.get_filter_list(),
            )

            with patch.object(statistics, "initialize", wraps=statistics.initialize) as initialize_spy:
                raw_first = json_provider.getJson()
                raw_second = json_provider.getJson()
                self.assertEqual(raw_first, raw_second)
                self.assertEqual(raw_first["unknownTopLevel"], {"preserve": "custom-value"})
                self.assertEqual(
                    raw_first["tasks"][0]["unknownTaskField"],
                    {"preserve": True},
                )
                self.assertNotIn(
                    "Define next action",
                    [task["description"] for task in raw_first["tasks"]],
                )

                work_view = TaskView(
                    filters=("Work",),
                    page=1,
                    page_size=5,
                    algorithm="GTD Algorithm",
                    heuristic="Remaining Effort(1)",
                )
                home_view = TaskView(
                    filters=("Home",),
                    page=1,
                    page_size=5,
                    algorithm="Shortest Job Algorithm",
                    heuristic="Start Time Heuristic",
                )
                work_result = application.query_tasks(work_view)
                home_result = application.query_tasks(home_view)
                work_again = application.query_tasks(work_view)
                combined_page_one = application.query_tasks(
                    TaskView(
                        filters=("Work", "Home"),
                        page=1,
                        page_size=1,
                        algorithm="Shortest Job Algorithm",
                        heuristic="Remaining Effort(1)",
                        search=("RELEASE", "OFFICE"),
                    )
                )
                combined_page_two = application.query_tasks(
                    TaskView(
                        filters=("Work", "Home"),
                        page=2,
                        page_size=1,
                        algorithm="Shortest Job Algorithm",
                        heuristic="Remaining Effort(1)",
                        search=("RELEASE", "OFFICE"),
                    )
                )
                combined_page_three = application.query_tasks(
                    TaskView(
                        filters=("Work", "Home"),
                        page=3,
                        page_size=1,
                        algorithm="Shortest Job Algorithm",
                        heuristic="Remaining Effort(1)",
                        search=("RELEASE", "OFFICE"),
                    )
                )
                search_with_defaults = application.query_tasks(TaskView(search=("PLAN", "OFFICE")))
                no_active_filters = application.query_tasks(
                    TaskView(filters=(), algorithm="", heuristic="")
                )

                work_tasks = {task.description: task for task in work_result.tasks}
                home_tasks = {task.description: task for task in home_result.tasks}
                self.assertIn("Review release draft", work_tasks)
                self.assertNotIn("Wait for reviewer", work_tasks)
                self.assertNotIn("Completed release archival task", work_tasks)
                self.assertEqual(set(home_tasks), {"Prepare home office"})
                self.assertIn("Urgent tasks (Work)", work_result.algorithm_desc)
                self.assertIn("Shortest Job First (SJF) Algorithm", home_result.algorithm_desc)
                self.assertIn("Urgent tasks (Work)", work_again.algorithm_desc)
                self.assertEqual(combined_page_one.total_tasks, 2)
                self.assertEqual(combined_page_two.total_tasks, 2)
                self.assertEqual(combined_page_one.total_pages, 2)
                self.assertEqual(combined_page_one.current_page, 1)
                self.assertEqual(combined_page_two.current_page, 2)
                self.assertEqual(len(combined_page_one.tasks), 1)
                self.assertEqual(len(combined_page_two.tasks), 1)
                self.assertEqual(
                    {combined_page_one.tasks[0].description, combined_page_two.tasks[0].description},
                    {"Review release draft", "Prepare home office"},
                )
                self.assertNotEqual(
                    combined_page_one.tasks[0].description,
                    combined_page_two.tasks[0].description,
                )
                self.assertEqual(combined_page_three.tasks, [])
                self.assertEqual(combined_page_three.total_tasks, 2)
                self.assertEqual(combined_page_three.total_pages, 2)
                # Search is an OR match over non-completed tasks; default
                # filters and strategies must not hide future or other-category matches.
                self.assertEqual(
                    {task.description for task in search_with_defaults.tasks},
                    {"Plan a future task", "Prepare home office"},
                )
                self.assertEqual(search_with_defaults.total_tasks, 2)
                self.assertEqual(search_with_defaults.algorithm_name, "None")
                self.assertEqual(search_with_defaults.sort_heuristic, "None")
                self.assertEqual(no_active_filters.tasks, [])
                self.assertEqual(no_active_filters.total_tasks, 0)

                # An ID returned by a query must resolve to the same task even
                # when completed rows precede it in storage.
                queried_open_task = work_tasks["Review release draft"]
                resolved_task = application.read_task(queried_open_task.id)
                self.assertEqual(resolved_task.getDescription(), queried_open_task.description)
                self.assertEqual(resolved_task.getStatus(), " ")

                completed = task_provider.getTaskList(include_completed=True)[0]
                completed_detail = application.read_task(completed.getTaskUID())
                self.assertEqual(completed_detail.getStatus(), "x")
                agenda = application.read_agenda(AgendaQuery(day=self.FIXED_NOW.strip_time()))
                self.assertIsNotNone(agenda)
                workload = channel_manager.get_list_stats()
                self.assertIsNotNone(workload)
                self.assertEqual(initialize_spy.call_count, 0)

            self.assertEqual(self._snapshot(data), original_files)
            self.assertFalse(statistics_path.exists())
            self.assertEqual(channel_manager.current_view(), channel_view_before_reads)
            self.assertIs(channel_manager.selected_task, selected_before_reads)
            self.assertEqual(
                [
                    (getattr(algorithm, "description", None), getattr(algorithm, "category", None))
                    for _, algorithm in algorithms
                ],
                algorithm_state_before_reads,
            )
            self.assertEqual(
                (
                    channel_manager.get_algorithm_list(),
                    channel_manager.get_heuristic_list(),
                    channel_manager.get_filter_list(),
                ),
                catalogs_before_reads,
            )
            self.assertNotEqual(channel_view_before_reads, original_view)
            task_provider.dispose()

    def test_markdown_record_work_uses_latest_target_effort_inside_write_turn(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            appdata = root / "appdata"
            vault = root / "vault"
            data.mkdir()
            appdata.mkdir()
            vault.mkdir()
            self._write_markdown_fixture(vault)
            coordinator = MutationCoordinator()
            file_broker = FileBroker(str(data), str(appdata), str(vault), coordinator)
            policies = TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="0",
                default_context="inbox",
                categories_prefixes=["alert", "work", "home", "inbox"],
            )
            json_provider = ObsidianVaultTaskJsonProvider(
                file_broker,
                policies,
                mutation_coordinator=coordinator,
                auto_start=False,
            )
            task_provider = ObsidianTaskProvider(
                json_provider,
                file_broker,
                disableThreading=True,
                mutation_coordinator=coordinator,
            )
            try:
                json_provider.refresh()
                application, _, _, _ = self._create_query_stack(file_broker, task_provider)
                target = next(
                    task
                    for task in task_provider.getTaskList(include_completed=True)
                    if "Review release draft" in task.getDescription()
                )
                task_id = target.getTaskUID()

                note_path = vault / "Atlas.md"
                note = note_path.read_text(encoding="utf-8")
                note_path.write_text(
                    note.replace(
                        "[remaining_cost::8] [invested::2]",
                        "[remaining_cost::6] [invested::4]",
                        1,
                    ),
                    encoding="utf-8",
                )

                result = application.execute_operation(
                    "record-work",
                    OperationTarget("task", task_id),
                    {"duration": "1p", "now": self.FIXED_NOW},
                )

                self.assertEqual(result.value.getInvestedEffort().as_pomodoros(), 5.0)
                self.assertEqual(result.value.getTotalCost().as_pomodoros(), 1.0)
                updated = task_provider.getTaskById(task_id)
                self.assertEqual(updated.getInvestedEffort().as_pomodoros(), 5.0)
                self.assertEqual(updated.getTotalCost().as_pomodoros(), 1.0)
            finally:
                task_provider.dispose()
                coordinator.close()

    def test_event_operations_recheck_waiters_from_the_current_note(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            appdata = root / "appdata"
            vault = root / "vault"
            data.mkdir()
            appdata.mkdir()
            vault.mkdir()
            self._write_markdown_fixture(vault)
            other_path = vault / "Other.md"
            other_path.write_text(
                "- [ ] Another waiter [track::work] [starts::2026-01-01] "
                "[due::2099-01-01] [severity::1] [remaining_cost::3] "
                "[invested::0] [calm::false] [waited::review-ready] [id::other-waiter]\n",
                encoding="utf-8",
            )
            coordinator = MutationCoordinator()
            broker = FileBroker(str(data), str(appdata), str(vault), coordinator)
            policies = TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="0",
                default_context="inbox",
                categories_prefixes=["alert", "work", "home", "inbox"],
            )
            json_provider = ObsidianVaultTaskJsonProvider(
                broker,
                policies,
                mutation_coordinator=coordinator,
                auto_start=False,
            )
            task_provider = ObsidianTaskProvider(
                json_provider,
                broker,
                disableThreading=True,
                mutation_coordinator=coordinator,
            )
            try:
                json_provider.refresh()
                application, _, _, _ = self._create_query_stack(broker, task_provider)
                tasks = task_provider.getTaskList(include_completed=True)
                raised = next(task for task in tasks if task.getEventRaised() == "review-ready")
                original_waiter = next(task for task in tasks if task.getTaskUID() == "other-waiter")
                original_start = original_waiter.getStart()

                atlas = vault / "Atlas.md"
                atlas_text = atlas.read_text(encoding="utf-8")
                atlas.write_text(
                    atlas_text.replace(
                        "[waited::review-ready]",
                        "[waited::different-event]",
                        1,
                    ),
                    encoding="utf-8",
                )
                other_path.write_text(
                    other_path.read_text(encoding="utf-8").replace(
                        "[waited::review-ready]",
                        "[waited::different-event]",
                        1,
                    ),
                    encoding="utf-8",
                )

                application.execute_operation(
                    "complete-task",
                    OperationTarget("task", raised.getTaskUID()),
                    {},
                )
                application.execute_operation(
                    "raise-event",
                    OperationTarget("event", "review-ready"),
                    {},
                )

                self.assertIn("[waited::different-event]", other_path.read_text(encoding="utf-8"))
                json_provider.refresh()
                self.assertEqual(
                    task_provider.getTaskById("other-waiter").getEventWaited(),
                    "different-event",
                )
                self.assertEqual(task_provider.getTaskById("other-waiter").getStart(), original_start)
            finally:
                task_provider.dispose()
                coordinator.close()

    def test_absent_json_and_statistics_files_remain_absent_on_reads(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            vault = root / "vault"
            vault.mkdir()
            tasks_path = data / "tasks.json"
            statistics_path = data / "statistics.json"

            file_broker = FileBroker(str(data), str(root / "appdata"), str(vault))
            task_provider = TaskProvider(TaskJsonProvider(file_broker), file_broker, disableThreading=True)
            application, channel_manager, statistics, _ = self._create_query_stack(
                file_broker,
                task_provider,
            )
            self.assertEqual(application.query_tasks(TaskView()).tasks, [])
            statistics.initialize()
            self.assertEqual(file_broker.readStatisticsFileContentJson().get("log"), [])
            self.assertEqual(channel_manager.get_list_stats().workload.as_pomodoros(), 0.0)

            self.assertFalse(tasks_path.exists())
            self.assertFalse(statistics_path.exists())
            task_provider.dispose()

    def test_markdown_queries_do_not_discover_or_rewrite_empty_projects(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            vault = root / "vault"
            vault.mkdir()
            self._write_markdown_fixture(vault)
            original_vault = self._snapshot(vault)
            statistics_path = data / "statistics.json"
            json_tasks_path = data / "tasks.json"

            file_broker = FileBroker(str(data), str(root / "appdata"), str(vault))
            policies = TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="0",
                default_context="inbox",
                categories_prefixes=["alert", "work", "home", "inbox"],
            )
            markdown_provider = ObsidianVaultTaskJsonProvider(
                file_broker,
                policies,
                auto_start=False,
            )
            markdown_provider.refresh()
            task_provider = ObsidianTaskProvider(markdown_provider, file_broker, disableThreading=True)
            application, channel_manager, statistics, algorithms = self._create_query_stack(
                file_broker,
                task_provider,
            )
            statistics.initialize()
            source_before_reads = markdown_provider.getJson()
            self.assertIn("EmptyOpen", [project["name"] for project in source_before_reads["projects"]])
            self.assertNotIn(
                "Define next action",
                [task["taskText"] for task in source_before_reads["tasks"]],
            )

            baseline_view = channel_manager.current_view()
            baseline_algorithms = [
                (getattr(algorithm, "description", None), getattr(algorithm, "category", None))
                for _, algorithm in algorithms
            ]
            with patch.object(statistics, "initialize", wraps=statistics.initialize) as initialize_spy:
                first = application.query_tasks(
                    TaskView(
                        filters=("Work",),
                        algorithm="GTD Algorithm",
                        heuristic="Remaining Effort(1)",
                    )
                )
                second = application.query_tasks(
                    TaskView(
                        filters=("Home",),
                        algorithm="EDF Algorithm",
                        heuristic="Start Time Heuristic",
                    )
                )
                completed = [
                    task for task in task_provider.getTaskList(include_completed=True)
                    if task.getStatus() == "x"
                ]
                self.assertTrue(completed)
                completed_detail = application.read_task(completed[0].getTaskUID())
                self.assertEqual(completed_detail.getStatus(), "x")
                agenda = application.read_agenda(AgendaQuery(day=self.FIXED_NOW.strip_time()))
                self.assertIsNotNone(agenda)
                workload = channel_manager.get_list_stats()
                self.assertIsNotNone(workload)
                self.assertTrue(any("Review release draft" in task.description for task in first.tasks))
                self.assertEqual(second.tasks, [])
                self.assertIn("GTD Task Algorithm", first.algorithm_desc)
                self.assertIn("Earliest Due Date (EDF) Algorithm", second.algorithm_desc)
                self.assertEqual(initialize_spy.call_count, 0)

            self.assertEqual(self._snapshot(vault), original_vault)
            self.assertFalse(statistics_path.exists())
            self.assertFalse(json_tasks_path.exists())
            self.assertEqual(channel_manager.current_view(), baseline_view)
            self.assertEqual(
                [
                    (getattr(algorithm, "description", None), getattr(algorithm, "category", None))
                    for _, algorithm in algorithms
                ],
                baseline_algorithms,
            )
            task_provider.dispose()

    def test_json_identity_is_lazy_stable_and_resolved_across_positions_and_completion(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            vault = root / "vault"
            vault.mkdir()
            tasks_path = data / "tasks.json"
            completed = self._base_task(
                description="Completed archival task",
                context="work:release",
                start=(self.FIXED_NOW + TimeAmount("-30d")).as_int(),
                due=(self.FIXED_NOW + TimeAmount("-1d")).as_int(),
                status="x",
                unknown={"keep": "completed"},
            )
            completed["id"] = "completed-task"
            target = self._base_task(
                description="Legacy JSON task",
                context="work:writing",
                start=(self.FIXED_NOW + TimeAmount("-1d")).as_int(),
                due=(self.FIXED_NOW + TimeAmount("3650d")).as_int(),
                unknown={"keep": "target"},
            )
            document = {
                "unknownTopLevel": {"keep": "top-level"},
                "tasks": [completed, target],
            }
            tasks_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

            file_broker = FileBroker(str(data), str(root / "appdata"), str(vault))
            task_provider = TaskProvider(TaskJsonProvider(file_broker), file_broker, disableThreading=True)
            application, _, _, _ = self._create_query_stack(file_broker, task_provider)
            target_id = fallback_task_id("Legacy JSON task", str(tasks_path), 1)

            before_reads = self._snapshot(data)
            self.assertEqual(application.read_task(target_id).getDescription(), "Legacy JSON task")
            self.assertEqual(application.read_task("completed-task").getStatus(), "x")
            with self.assertRaises(ResourceNotFoundError):
                application.read_task("no-such-task")
            self.assertEqual(self._snapshot(data), before_reads)
            self.assertNotIn("id", json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"][1])

            updated = application.edit_task(target_id, {"description": "Renamed JSON task"})
            self.assertEqual(updated.getTaskUID(), target_id)
            saved = json.loads(tasks_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["unknownTopLevel"], {"keep": "top-level"})
            self.assertEqual(saved["tasks"][1]["id"], target_id)
            self.assertEqual(saved["tasks"][1]["description"], "Renamed JSON task")
            self.assertEqual(saved["tasks"][1]["unknownTaskField"], {"keep": "target"})
            self.assertEqual(saved["tasks"][0]["unknownTaskField"], {"keep": "completed"})

            # Moving a persisted row changes its physical position but not its ID.
            saved["tasks"] = [saved["tasks"][1], saved["tasks"][0]]
            tasks_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
            before_repeated_read = self._snapshot(data)
            self.assertEqual(application.read_task(target_id).getDescription(), "Renamed JSON task")
            self.assertEqual(self._snapshot(data), before_repeated_read)
            completed_result = application.execute_operation(
                "complete-task",
                OperationTarget("task", target_id),
                {},
            )
            self.assertEqual(completed_result.affected_ids, (target_id,))
            self.assertEqual(application.read_task(target_id).getStatus(), "x")
            saved_after_completion = json.loads(tasks_path.read_text(encoding="utf-8"))
            completed_target = next(task for task in saved_after_completion["tasks"] if task.get("id") == target_id)
            self.assertEqual(completed_target["unknownTaskField"], {"keep": "target"})

            # A copied identity makes every write to that identifier ambiguous.
            saved_after_completion["tasks"][1]["id"] = target_id
            tasks_path.write_text(json.dumps(saved_after_completion, indent=2), encoding="utf-8")
            ambiguous_snapshot = self._snapshot(data)
            with self.assertRaises(AmbiguousResourceError):
                application.edit_task(target_id, {"description": "Must not be written"})
            self.assertEqual(self._snapshot(data), ambiguous_snapshot)

            saved_after_completion["tasks"][1]["id"] = "completed-task"
            invalid_record = self._base_task(
                description="Invalid declared ID",
                context="work:ops",
                start=self.FIXED_NOW.as_int(),
                due=(self.FIXED_NOW + TimeAmount("1d")).as_int(),
            )
            invalid_record["id"] = 17
            saved_after_completion["tasks"].append(invalid_record)
            tasks_path.write_text(json.dumps(saved_after_completion, indent=2), encoding="utf-8")
            invalid_snapshot = self._snapshot(data)
            with self.assertRaises(InvalidResourceDataError):
                application.read_task(target_id)
            self.assertEqual(self._snapshot(data), invalid_snapshot)
            task_provider.dispose()

    def test_json_schedule_keeps_source_identity_and_assigns_distinct_part_ids(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            vault = root / "vault"
            vault.mkdir()
            tasks_path = data / "tasks.json"
            source = self._base_task(
                description="Split this task",
                context="work:writing",
                start=(self.FIXED_NOW + TimeAmount("-1d")).as_int(),
                due=(self.FIXED_NOW + TimeAmount("3650d")).as_int(),
                unknown={"keep": "source"},
            )
            source["id"] = "source-id"
            tasks_path.write_text(
                json.dumps({"customDocumentData": {"keep": True}, "tasks": [source]}, indent=2),
                encoding="utf-8",
            )
            file_broker = FileBroker(str(data), str(root / "appdata"), str(vault))
            task_provider = TaskProvider(TaskJsonProvider(file_broker), file_broker, disableThreading=True)
            application, _, _, _ = self._create_query_stack(
                file_broker,
                task_provider,
                scheduling=HeuristicScheduling(TimeAmount("5p"), task_provider),
            )

            result = application.execute_operation(
                "schedule-task",
                OperationTarget("task", "source-id"),
                {"effort_per_day": "11p"},
            )

            document = json.loads(tasks_path.read_text(encoding="utf-8"))
            ids = [task["id"] for task in document["tasks"]]
            self.assertEqual(result.affected_ids, tuple(ids))
            self.assertGreater(len(ids), 1)
            self.assertEqual(ids[0], "source-id")
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(document["customDocumentData"], {"keep": True})
            self.assertEqual(document["tasks"][0]["unknownTaskField"], {"keep": "source"})
            for task_id in ids:
                self.assertEqual(application.read_task(task_id).getTaskUID(), task_id)
            task_provider.dispose()

    def test_markdown_identity_survives_edits_and_moves_and_rejects_ambiguous_or_invalid_data(self) -> None:
        with self._fixed_clock(), TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            vault = root / "vault"
            vault.mkdir()
            start = str((self.FIXED_NOW + TimeAmount("-1d")).strip_time())
            due = str((self.FIXED_NOW + TimeAmount("3650d")).strip_time())
            source_path = vault / "Notes.md"
            source_path.write_text(
                "# Notes\n"
                f"- [ ] Legacy markdown task [track::work] [starts::{start}] [due::{due}] "
                "[severity::1] [remaining_cost::8] [invested::2] [calm::false] [custom::keep]\n"
                f"- [x] Completed markdown task [track::work] [starts::{start}] [due::{due}] "
                "[severity::1] [remaining_cost::2] [invested::2] [calm::false] [id:: completed-markdown]\n",
                encoding="utf-8",
            )
            file_broker = FileBroker(str(data), str(root / "appdata"), str(vault))
            policies = TaskDiscoveryPolicies(
                context_missing_policy="0",
                date_missing_policy="0",
                default_context="work",
                categories_prefixes=["work"],
            )
            markdown_json = ObsidianVaultTaskJsonProvider(
                file_broker,
                policies,
                auto_start=False,
            )
            markdown_json.refresh()
            task_provider = ObsidianTaskProvider(markdown_json, file_broker, disableThreading=True)
            application, _, _, _ = self._create_query_stack(
                file_broker,
                task_provider,
                scheduling=HeuristicScheduling(TimeAmount("5p"), task_provider),
            )
            target = next(
                task for task in task_provider.getTaskList(include_completed=True)
                if task.getTaskText() == "Legacy markdown task"
            )
            target_id = fallback_task_id("Legacy markdown task", "Notes.md", target.getLine())
            self.assertEqual(target.getTaskUID(), target_id)
            self.assertEqual(application.read_task("completed-markdown").getStatus(), "x")
            before_reads = self._snapshot(vault)
            with patch.object(
                task_provider,
                "getTaskList",
                side_effect=AssertionError("indexed detail must not rebuild the full task list"),
            ):
                detail = ApiResources(application).read_task(target_id)
            self.assertEqual(detail["id"], target_id)
            self.assertEqual(self._snapshot(vault), before_reads)

            application.edit_task(target_id, {"description": "Updated markdown task"})
            updated_lines = source_path.read_text(encoding="utf-8")
            self.assertIn(f"[id:: {target_id}]", updated_lines)
            self.assertIn("[custom::keep]", updated_lines)
            self.assertEqual(application.read_task(target_id).getTaskUID(), target_id)

            source_lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
            moved_line = next(line for line in source_lines if f"[id:: {target_id}]" in line)
            source_path.write_text("".join(line for line in source_lines if line != moved_line), encoding="utf-8")
            moved_path = vault / "Moved.md"
            moved_path.write_text("# Moved\n" + moved_line, encoding="utf-8")
            markdown_json.refresh()
            before_move_read = self._snapshot(vault)
            resolved_after_move = application.read_task(target_id)
            self.assertEqual(resolved_after_move.getFile(), "Moved.md")
            self.assertEqual(self._snapshot(vault), before_move_read)
            application.edit_task(target_id, {"context": "work:edited"})
            self.assertIn(f"[id:: {target_id}]", moved_path.read_text(encoding="utf-8"))
            self.assertIn("[custom::keep]", moved_path.read_text(encoding="utf-8"))

            split = application.execute_operation(
                "schedule-task",
                OperationTarget("task", target_id),
                {"effort_per_day": "11p"},
            )
            split_ids = split.affected_ids
            self.assertGreater(len(split_ids), 1)
            self.assertEqual(split_ids[0], target_id)
            self.assertEqual(len(split_ids), len(set(split_ids)))
            all_ids = [task.getTaskUID() for task in task_provider.getTaskList(include_completed=True)]
            self.assertEqual(len(all_ids), len(set(all_ids)))

            duplicate_path = vault / "Duplicate.md"
            moved_line = next(
                line for line in moved_path.read_text(encoding="utf-8").splitlines(keepends=True)
                if f"[id:: {target_id}]" in line
            )
            duplicate_path.write_text("# Duplicate\n" + moved_line, encoding="utf-8")
            markdown_json.refresh()
            duplicate_snapshot = self._snapshot(vault)
            with self.assertRaises(AmbiguousResourceError):
                application.edit_task(target_id, {"description": "Must not be written"})
            self.assertEqual(self._snapshot(vault), duplicate_snapshot)

            invalid_path = vault / "Invalid.md"
            invalid_path.write_text(
                f"- [ ] Invalid identity [track::work] [starts::{start}] [due::{due}] "
                "[severity::1] [remaining_cost::1] [invested::0] [calm::false] [id:: ]\n",
                encoding="utf-8",
            )
            markdown_json.refresh()
            invalid_snapshot = self._snapshot(vault)
            with self.assertRaises(InvalidResourceDataError):
                application.read_task(target_id)
            self.assertEqual(self._snapshot(vault), invalid_snapshot)
            task_provider.dispose()
