import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
import datetime
from copy import deepcopy

from src.FileBroker import FileBroker
from src.StatisticsService import StatisticsService, StatisticsUpdateError
from src.Interfaces.IFileBroker import FileRegistry
from src.Utils import WorkLogEntry
from src.filters.ActiveTaskFilter import ActiveTaskFilter
from src.filters.WorkloadAbleFilter import WorkloadAbleFilter
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.heuristics.SlackHeuristic import SlackHeuristic
from src.taskmodels.TaskModel import TaskModel
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestStatisticsService(unittest.TestCase):
    def setUp(self):
        # Create mock objects
        self.mock_file_broker = Mock()
        self.mock_workload_filter = Mock()
        self.mock_remaining_effort_heuristic = Mock()
        self.mock_main_heuristic = Mock()
        self.mock_task = Mock()

        self.stats_document = {}

        def update_statistics(registry, updater):
            updated = updater(deepcopy(self.stats_document))
            self.mock_file_broker.writeFileContentJson(registry, updated)
            self.stats_document = deepcopy(updated)
            return deepcopy(updated)

        self.mock_file_broker.updateFileContentJson.side_effect = update_statistics

        # Configure mock task
        self.mock_task.getDescription.return_value = "Test Task"
        self.mock_task.getTotalCost.return_value = TimeAmount("4p")
        self.mock_task.calculateRemainingTime.return_value = TimeAmount("2d")

        # Create the service with mocks
        self.service = StatisticsService(
            self.mock_file_broker,
            self.mock_workload_filter,
            self.mock_remaining_effort_heuristic,
            self.mock_main_heuristic
        )

    @staticmethod
    def _task(
        description: str,
        *,
        due_day: int,
        start_day: int = 6,
        status: str = " ",
        waited: str | None = None,
        total_cost: float = 4.0,
        severity: float = 1.0,
        model_type: type[TaskModel] = TaskModel,
    ) -> TaskModel:
        start = datetime.datetime(2026, 10, start_day, 12, 0).timestamp() * 1000
        due = datetime.datetime(2026, 10, due_day, 0, 0).timestamp() * 1000
        return model_type(
            description,
            "work:test",
            int(start),
            int(due),
            severity,
            total_cost,
            -0.5,
            status,
            "false",
            "",
            0,
            None,
            waited,
        )

    @staticmethod
    def _built_in_service(remaining_type=RemainingEffortHeuristic, slack_type=SlackHeuristic):
        remaining = remaining_type(TimeAmount("2p"), 1.0)
        slack = slack_type(TimeAmount("2p"))
        return StatisticsService(
            Mock(),
            WorkloadAbleFilter(ActiveTaskFilter()),
            remaining,
            slack,
        )

    def test_builtin_statistics_reuse_remaining_days_at_fixed_clock_boundaries(self):
        class LegacyTaskModel(TaskModel):
            def calculateRemainingTime(self):
                return super().calculateRemainingTime()

        task_values = [
            ("First tied workload", 8, 4.0, 1.0, 6, " ", None),
            ("Second tied workload", 8, 4.0, 1.0, 6, " ", None),
            ("Fractional cost", 9, 4.5, 0.6, 6, " ", None),
            ("Near deadline", 7, 2.25, 1.5, 6, " ", None),
            ("Urgent", 6, 8.0, 1.0, 6, " ", None),
            ("Negative cost", 9, -1.25, 1.0, 6, " ", None),
            ("Waiting", 9, 3.0, 1.0, 6, " ", "external-event"),
            ("Future start", 9, 3.0, 1.0, 7, " ", None),
            ("Completed", 9, 3.0, 1.0, 6, "x", None),
        ]
        optimized_tasks = [
            self._task(
                description,
                due_day=due_day,
                total_cost=cost,
                severity=severity,
                start_day=start_day,
                status=status,
                waited=waited,
            )
            for description, due_day, cost, severity, start_day, status, waited in task_values
        ]
        legacy_tasks = [
            self._task(
                description,
                due_day=due_day,
                total_cost=cost,
                severity=severity,
                start_day=start_day,
                status=status,
                waited=waited,
                model_type=LegacyTaskModel,
            )
            for description, due_day, cost, severity, start_day, status, waited in task_values
        ]
        optimized_service = self._built_in_service()
        legacy_service = self._built_in_service()
        instants = (
            datetime.datetime(2026, 10, 6, 23, 59, 59, 999000),
            datetime.datetime(2026, 10, 7, 0, 0, 0),
        )
        optimized_results = []

        for instant in instants:
            fixed_now = TimePoint(instant)
            with patch.object(TimePoint, "now", return_value=fixed_now):
                optimized = optimized_service.getWorkloadStats(optimized_tasks)
            with patch.object(TimePoint, "now", return_value=fixed_now):
                legacy = legacy_service.getWorkloadStats(legacy_tasks)

            self.assertEqual(optimized, legacy)
            optimized_results.append(optimized)
        self.assertEqual(optimized_results[0].offender, "Near deadline")
        self.assertEqual(optimized_results[1].offender, "First tied workload")

    def test_builtin_statistics_calculate_remaining_time_once_per_active_task(self):
        tasks = [
            self._task("One", due_day=8),
            self._task("Two", due_day=9),
            self._task("Urgent", due_day=6),
            self._task("Future", due_day=9, start_day=7),
            self._task("Complete", due_day=9, status="x"),
            self._task("Waiting", due_day=9, waited="external-event"),
        ]
        service = self._built_in_service()
        original_calculate = TaskModel.calculateRemainingTime
        fixed_now = TimePoint(datetime.datetime(2026, 10, 6, 23, 59, 59, 999000))

        with patch.object(TimePoint, "now", return_value=fixed_now), patch.object(
            TaskModel,
            "calculateRemainingTime",
            autospec=True,
            side_effect=original_calculate,
        ) as calculate_remaining:
            service.getWorkloadStats(tasks)

        # The active filter excludes future and completed work; each remaining
        # active task is evaluated once, even when several stats use its days.
        self.assertEqual(calculate_remaining.call_count, 4)

    def test_custom_statistics_heuristic_keeps_uncached_call_behavior(self):
        class CustomRemainingEffortHeuristic(RemainingEffortHeuristic):
            pass

        task = self._task("Custom stats", due_day=8)
        service = self._built_in_service(remaining_type=CustomRemainingEffortHeuristic)
        original_calculate = TaskModel.calculateRemainingTime
        fixed_now = TimePoint(datetime.datetime(2026, 10, 6, 23, 59, 59, 999000))

        with patch.object(TimePoint, "now", return_value=fixed_now), patch.object(
            TaskModel,
            "calculateRemainingTime",
            autospec=True,
            side_effect=original_calculate,
        ) as calculate_remaining:
            service.getWorkloadStats([task])

        # The workload filter, two configured heuristics, and workload formula
        # keep their legacy independent calls for custom extension types.
        self.assertEqual(calculate_remaining.call_count, 4)

    def test_do_work(self):
        # Arrange
        test_date = datetime.date(2023, 1, 1)
        work_units = TimeAmount("2.5p")

        # Act
        with patch('src.wrappers.TimeManagement.TimePoint.now') as mock_now:
            mock_now.return_value.as_int.return_value = 1672531200000  # 2023-01-01
            mock_now.return_value.__str__.return_value = "2023-01-01"
            self.service.doWork(test_date, work_units, self.mock_task)

        # Assert
        self.assertEqual(self.service.workDone[test_date.isoformat()], work_units.as_pomodoros())
        self.mock_file_broker.updateFileContentJson.assert_called_once()
        self.mock_file_broker.writeFileContentJson.assert_called_once_with(
            FileRegistry.STATISTICS_JSON,
            self.stats_document,
        )
        self.assertIsInstance(self.service.workDone["log"][0], WorkLogEntry)

    def test_do_work_accumulates_work(self):
        # Arrange
        test_date = datetime.date(2023, 1, 1)
        initial_work = TimeAmount("1.6p")
        additional_work = TimeAmount("2.0p")
        self.stats_document = {test_date.isoformat(): initial_work.as_pomodoros()}

        # Act
        with patch('src.wrappers.TimeManagement.TimePoint.now') as mock_now:
            mock_now.return_value.as_int.return_value = 1672531200000
            mock_now.return_value.__str__.return_value = "2023-01-01"
            self.service.doWork(test_date, additional_work, self.mock_task)

        # Assert
        self.assertEqual(self.service.workDone[test_date.isoformat()], initial_work.as_pomodoros() + additional_work.as_pomodoros())

    def test_get_work_done_log(self):
        # Arrange
        log_entries = [
            {"timestamp": 1672531200000, "work_units": 2.0, "task": "Task 1"},
            {"timestamp": 1672534800000, "work_units": 1.5, "task": "Task 2"}
        ]
        self.service.workDone = {"log": log_entries}

        # Act
        result = self.service.getWorkDoneLog()

        # Assert
        self.assertEqual(result, [WorkLogEntry(**entry) for entry in log_entries])

    def test_read_workload_stats_uses_fresh_file_snapshot_without_changing_cache(self):
        self.service.workDone = {"2026-10-04": 1.0}
        fresh_log = [{"timestamp": 1791115200000, "work_units": 2.5, "task": "Fresh task"}]
        self.mock_file_broker.readStatisticsFileContentJson.return_value = {
            "2026-10-05": 4.25,
            "log": fresh_log,
        }
        self.mock_workload_filter.filter.return_value = []

        result = self.service.readWorkloadStats([])

        self.assertEqual(result.workDone, {"2026-10-05": 4.25})
        self.assertEqual(result.workDoneLog, [WorkLogEntry(**fresh_log[0])])
        self.assertEqual(self.service.workDone, {"2026-10-04": 1.0})
        self.mock_file_broker.readStatisticsFileContentJson.assert_called_once_with()

    def test_do_work_preserves_unknown_statistics_and_log_fields(self):
        test_date = datetime.date(2023, 1, 1)
        self.stats_document = {
            test_date.isoformat(): 1,
            "future_metric": {"keep": True},
            "log": [{
                "timestamp": 1672531100000,
                "work_units": 0.5,
                "task": "Earlier task",
                "source": "external",
            }],
        }

        with patch("src.wrappers.TimeManagement.TimePoint.now") as mock_now:
            mock_now.return_value.as_int.return_value = 1672531200000
            mock_now.return_value.__str__.return_value = "2023-01-01"
            self.service.doWork(test_date, TimeAmount("2p"), self.mock_task)

        self.assertEqual(self.stats_document["future_metric"], {"keep": True})
        self.assertEqual(self.stats_document["log"][0]["source"], "external")
        self.assertEqual(self.service.workDone[test_date.isoformat()], 3.0)
        self.assertIsInstance(self.service.workDone["log"][0], WorkLogEntry)

    def test_do_work_does_not_publish_cache_when_callback_rejects_invalid_latest_document(self):
        self.stats_document = {"log": "invalid"}
        published_before = deepcopy(self.service.workDone)

        with patch("src.wrappers.TimeManagement.TimePoint.now") as mock_now:
            mock_now.return_value.as_int.return_value = 1672531200000
            with self.assertRaises(StatisticsUpdateError):
                self.service.doWork(datetime.date(2023, 1, 1), TimeAmount("2p"), self.mock_task)

        self.assertEqual(self.service.workDone, published_before)
        self.mock_file_broker.writeFileContentJson.assert_not_called()

    def test_initialize_propagates_invalid_statistics_instead_of_using_empty_cache(self):
        self.mock_file_broker.readStatisticsFileContentJson.side_effect = ValueError("invalid statistics")

        with self.assertRaisesRegex(ValueError, "invalid statistics"):
            self.service.initialize()

    def test_work_log_entry_deepcopy_preserves_fields_and_legacy_serialization(self):
        entry = WorkLogEntry(timestamp=1672531200000, work_units=2.25, task="Original task")

        copied = deepcopy(entry)
        copied.task = "Changed copy"

        self.assertIsNot(copied, entry)
        self.assertEqual(copied.__dict__(), {
            "timestamp": 1672531200000,
            "work_units": 2.25,
            "task": "Changed copy",
        })
        self.assertEqual(entry.__dict__(), {
            "timestamp": 1672531200000,
            "work_units": 2.25,
            "task": "Original task",
        })

    def test_initialize_copies_real_file_broker_log_and_keeps_json_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            stats_path = os.path.join(directory, "statistics.json")
            source_document = {
                "2026-10-06": 1.5,
                "future_metric": {"keep": True},
                "log": [{
                    "timestamp": 1791288000000,
                    "work_units": 2.25,
                    "task": "Original task",
                }],
            }
            with open(stats_path, "w", encoding="utf-8") as stats_file:
                json.dump(source_document, stats_file)

            source_data = broker.readStatisticsFileContentJson()
            service = StatisticsService(
                broker,
                self.mock_workload_filter,
                self.mock_remaining_effort_heuristic,
                self.mock_main_heuristic,
            )
            with patch.object(broker, "readStatisticsFileContentJson", return_value=source_data):
                service.initialize()

            self.assertIsInstance(source_data["log"][0], WorkLogEntry)
            self.assertIsInstance(service.workDone["log"][0], WorkLogEntry)
            self.assertIsNot(service.workDone, source_data)
            self.assertIsNot(service.workDone["log"], source_data["log"])
            self.assertIsNot(service.workDone["log"][0], source_data["log"][0])
            service.workDone["log"][0].task = "Updated task"
            self.assertEqual(source_data["log"][0].task, "Original task")

            broker.writeFileContentJson(FileRegistry.STATISTICS_JSON, service.workDone)
            with open(stats_path, "r", encoding="utf-8") as stats_file:
                saved_document = json.load(stats_file)

            self.assertEqual(saved_document, {
                "2026-10-06": 1.5,
                "future_metric": {"keep": True},
                "log": [{
                    "timestamp": 1791288000000,
                    "work_units": 2.25,
                    "task": "Updated task",
                }],
            })

    def test_getEventStatistics_empty_task_list(self):
        # Arrange
        task_list = []

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 0)
        self.assertEqual(result.total_raising_tasks, 0)
        self.assertEqual(result.total_waiting_tasks, 0)
        self.assertEqual(result.orphaned_events_count, 0)
        self.assertEqual(len(result.event_statistics), 0)

    def test_getEventStatistics_no_events(self):
        # Arrange
        mock_task1 = Mock()
        mock_task1.getEventRaised.return_value = None
        mock_task1.getEventWaited.return_value = None
        
        mock_task2 = Mock()
        mock_task2.getEventRaised.return_value = None
        mock_task2.getEventWaited.return_value = None
        
        task_list = [mock_task1, mock_task2]

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 0)
        self.assertEqual(result.total_raising_tasks, 0)
        self.assertEqual(result.total_waiting_tasks, 0)
        self.assertEqual(result.orphaned_events_count, 0)
        self.assertEqual(len(result.event_statistics), 0)

    def test_getEventStatistics_balanced_events(self):
        # Arrange
        mock_task1 = Mock()
        mock_task1.getEventRaised.return_value = "event_A"
        mock_task1.getEventWaited.return_value = None
        
        mock_task2 = Mock()
        mock_task2.getEventRaised.return_value = None
        mock_task2.getEventWaited.return_value = "event_A"
        
        task_list = [mock_task1, mock_task2]

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 1)
        self.assertEqual(result.total_raising_tasks, 1)
        self.assertEqual(result.total_waiting_tasks, 1)
        self.assertEqual(result.orphaned_events_count, 0)
        self.assertEqual(len(result.event_statistics), 1)
        
        event_stat = result.event_statistics[0]
        self.assertEqual(event_stat.event_name, "event_A")
        self.assertEqual(event_stat.tasks_raising, 1)
        self.assertEqual(event_stat.tasks_waiting, 1)
        self.assertFalse(event_stat.is_orphaned)
        self.assertEqual(event_stat.orphan_type, "none")

    def test_getEventStatistics_orphaned_raised_only(self):
        # Arrange
        mock_task1 = Mock()
        mock_task1.getEventRaised.return_value = "orphaned_event"
        mock_task1.getEventWaited.return_value = None
        
        mock_task2 = Mock()
        mock_task2.getEventRaised.return_value = "orphaned_event"
        mock_task2.getEventWaited.return_value = None
        
        task_list = [mock_task1, mock_task2]

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 1)
        self.assertEqual(result.total_raising_tasks, 2)
        self.assertEqual(result.total_waiting_tasks, 0)
        self.assertEqual(result.orphaned_events_count, 1)
        self.assertEqual(len(result.event_statistics), 1)
        
        event_stat = result.event_statistics[0]
        self.assertEqual(event_stat.event_name, "orphaned_event")
        self.assertEqual(event_stat.tasks_raising, 2)
        self.assertEqual(event_stat.tasks_waiting, 0)
        self.assertTrue(event_stat.is_orphaned)
        self.assertEqual(event_stat.orphan_type, "raised_only")

    def test_getEventStatistics_orphaned_waited_only(self):
        # Arrange
        mock_task1 = Mock()
        mock_task1.getEventRaised.return_value = None
        mock_task1.getEventWaited.return_value = "waiting_event"
        
        mock_task2 = Mock()
        mock_task2.getEventRaised.return_value = None
        mock_task2.getEventWaited.return_value = "waiting_event"
        
        task_list = [mock_task1, mock_task2]

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 1)
        self.assertEqual(result.total_raising_tasks, 0)
        self.assertEqual(result.total_waiting_tasks, 2)
        self.assertEqual(result.orphaned_events_count, 1)
        self.assertEqual(len(result.event_statistics), 1)
        
        event_stat = result.event_statistics[0]
        self.assertEqual(event_stat.event_name, "waiting_event")
        self.assertEqual(event_stat.tasks_raising, 0)
        self.assertEqual(event_stat.tasks_waiting, 2)
        self.assertTrue(event_stat.is_orphaned)
        self.assertEqual(event_stat.orphan_type, "waited_only")

    def test_getEventStatistics_multiple_events_complex(self):
        # Arrange
        mock_task1 = Mock()
        mock_task1.getEventRaised.return_value = "event_A"
        mock_task1.getEventWaited.return_value = "event_B"
        
        mock_task2 = Mock()
        mock_task2.getEventRaised.return_value = "event_B"
        mock_task2.getEventWaited.return_value = "event_A"
        
        mock_task3 = Mock()
        mock_task3.getEventRaised.return_value = "orphaned_raised"
        mock_task3.getEventWaited.return_value = None
        
        mock_task4 = Mock()
        mock_task4.getEventRaised.return_value = None
        mock_task4.getEventWaited.return_value = "orphaned_waited"
        
        task_list = [mock_task1, mock_task2, mock_task3, mock_task4]

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 4)
        self.assertEqual(result.total_raising_tasks, 3)
        self.assertEqual(result.total_waiting_tasks, 3)
        self.assertEqual(result.orphaned_events_count, 2)
        self.assertEqual(len(result.event_statistics), 4)
        
        # Events should be sorted alphabetically
        event_names = [stat.event_name for stat in result.event_statistics]
        self.assertEqual(event_names, ["event_A", "event_B", "orphaned_raised", "orphaned_waited"])
        
        # Check specific events
        event_a = next(stat for stat in result.event_statistics if stat.event_name == "event_A")
        self.assertEqual(event_a.tasks_raising, 1)
        self.assertEqual(event_a.tasks_waiting, 1)
        self.assertFalse(event_a.is_orphaned)
        
        event_b = next(stat for stat in result.event_statistics if stat.event_name == "event_B")
        self.assertEqual(event_b.tasks_raising, 1)
        self.assertEqual(event_b.tasks_waiting, 1)
        self.assertFalse(event_b.is_orphaned)
        
        orphaned_raised = next(stat for stat in result.event_statistics if stat.event_name == "orphaned_raised")
        self.assertEqual(orphaned_raised.tasks_raising, 1)
        self.assertEqual(orphaned_raised.tasks_waiting, 0)
        self.assertTrue(orphaned_raised.is_orphaned)
        self.assertEqual(orphaned_raised.orphan_type, "raised_only")
        
        orphaned_waited = next(stat for stat in result.event_statistics if stat.event_name == "orphaned_waited")
        self.assertEqual(orphaned_waited.tasks_raising, 0)
        self.assertEqual(orphaned_waited.tasks_waiting, 1)
        self.assertTrue(orphaned_waited.is_orphaned)
        self.assertEqual(orphaned_waited.orphan_type, "waited_only")

    def test_getEventStatistics_same_task_multiple_same_event(self):
        # Arrange - Test edge case where task both raises and waits for the same event
        mock_task1 = Mock()
        mock_task1.getEventRaised.return_value = "self_event"
        mock_task1.getEventWaited.return_value = "self_event"
        
        task_list = [mock_task1]

        # Act
        result = self.service.getEventStatistics(task_list)

        # Assert
        self.assertEqual(result.total_events, 1)
        self.assertEqual(result.total_raising_tasks, 1)
        self.assertEqual(result.total_waiting_tasks, 1)
        self.assertEqual(result.orphaned_events_count, 0)
        self.assertEqual(len(result.event_statistics), 1)
        
        event_stat = result.event_statistics[0]
        self.assertEqual(event_stat.event_name, "self_event")
        self.assertEqual(event_stat.tasks_raising, 1)
        self.assertEqual(event_stat.tasks_waiting, 1)
        self.assertFalse(event_stat.is_orphaned)
        self.assertEqual(event_stat.orphan_type, "none")


if __name__ == '__main__':
    unittest.main()
