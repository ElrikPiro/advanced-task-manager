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
        work_units = 2.5

        # Act
        with patch('src.wrappers.TimeManagement.TimePoint.now') as mock_now:
            mock_now.return_value.as_int.return_value = 1672531200000  # 2023-01-01
            mock_now.return_value.__str__.return_value = "2023-01-01"
            self.service.doWork(test_date, work_units, self.mock_task)

        # Assert
        self.assertEqual(self.service.workDone[test_date.isoformat()], work_units)
        self.mock_file_broker.writeFileContentJson.assert_called_once_with(
            FileRegistry.STATISTICS_JSON, self.service.workDone
        )

    def test_do_work_accumulates_work(self):
        # Arrange
        test_date = datetime.date(2023, 1, 1)
        initial_work = 1.5
        additional_work = 2.0
        self.service.workDone = {test_date.isoformat(): initial_work}

        # Act
        with patch('src.wrappers.TimeManagement.TimePoint.now') as mock_now:
            mock_now.return_value.as_int.return_value = 1672531200000
            mock_now.return_value.__str__.return_value = "2023-01-01"
            self.service.doWork(test_date, additional_work, self.mock_task)

        # Assert
        self.assertEqual(self.service.workDone[test_date.isoformat()], initial_work + additional_work)

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


if __name__ == '__main__':
    unittest.main()
