"""Integration checks for read-only application queries."""

import datetime
import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator
from unittest import TestCase
from unittest.mock import patch

from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry
from src.StatisticsService import StatisticsService
from src.TelegramTaskListManager import TelegramTaskListManager
from src.Utils import TaskDiscoveryPolicies
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.algorithms.GtdAlgorithm import GtdAlgorithm
from src.algorithms.ShortestJobAlgorithm import ShortestJobAlgorithm
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.models import AgendaQuery, TaskView
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
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.taskproviders.TaskProvider import TaskProvider
from src.wrappers.TimeManagement import TimeAmount, TimePoint


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

    def _create_query_stack(self, file_broker: FileBroker, task_provider):
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
            scheduling=None,
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
                # Q-011 search is an OR match over every non-completed task;
                # the default active filter and GTD strategy must not hide a
                # future task or a match in another category.
                self.assertEqual(
                    {task.description for task in search_with_defaults.tasks},
                    {"Plan a future task", "Prepare home office"},
                )
                self.assertEqual(search_with_defaults.total_tasks, 2)
                self.assertEqual(search_with_defaults.algorithm_name, "None")
                self.assertEqual(search_with_defaults.sort_heuristic, "None")
                self.assertEqual(no_active_filters.tasks, [])
                self.assertEqual(no_active_filters.total_tasks, 0)

                # Query IDs are currently provisional, but a response must still
                # resolve to the same physical task when a completed task is before it.
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
            markdown_provider = ObsidianVaultTaskJsonProvider(file_broker, policies)
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
