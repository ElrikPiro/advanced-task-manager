import unittest
from unittest.mock import Mock, patch
import datetime

from src.StatisticsService import StatisticsService
from src.Interfaces.IFileBroker import FileRegistry
from src.wrappers.TimeManagement import TimeAmount


class TestStatisticsService(unittest.TestCase):
    def setUp(self):
        # Create mock objects
        self.mock_file_broker = Mock()
        self.mock_workload_filter = Mock()
        self.mock_remaining_effort_heuristic = Mock()
        self.mock_main_heuristic = Mock()
        self.mock_task = Mock()

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
        self.mock_file_broker.writeFileContentJson.assert_called_once_with(
            FileRegistry.STATISTICS_JSON, self.service.workDone
        )

    def test_do_work_accumulates_work(self):
        # Arrange
        test_date = datetime.date(2023, 1, 1)
        initial_work = TimeAmount("1.6p")
        additional_work = TimeAmount("2.0p")
        self.service.workDone = {test_date.isoformat(): initial_work.as_pomodoros()}

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
        self.assertEqual(result, log_entries)

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
