import unittest
from unittest.mock import MagicMock
from src.TelegramTaskListManager import TelegramTaskListManager
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestTelegramTaskListManager(unittest.TestCase):

    def setUp(self):
        # Create mock task models
        self.task1 = MagicMock()
        self.task1.getDescription.return_value = "Task 1"
        self.task1.getStatus.return_value = ""

        self.task2 = MagicMock()
        self.task2.getDescription.return_value = "Task 2"
        self.task2.getStatus.return_value = ""

        self.task_list = [self.task1, self.task2]

        # Create mock statistics service
        self.statistics_service = MagicMock()

        # Create mock heuristics and filters
        self.heuristics = [("Priority", MagicMock())]
        self.filters = [("Active", MagicMock())]

        # Create the task list manager
        self.task_list_manager = TelegramTaskListManager(
            self.task_list,
            self.heuristics,
            self.filters,
            self.statistics_service
        )

    def test_get_list_stats(self):
        # Arrange
        # Set up getWorkDone to return different values for different dates
        work_done_values = {
            0: TimeAmount("2p"),
            1: TimeAmount("3p"),
            2: TimeAmount("1.5p"),
            3: TimeAmount("0p"),
            4: TimeAmount("2.5p"),
            5: TimeAmount("1p"),
            6: TimeAmount("4p")
        }

        def mock_get_work_done(date):
            # Find which day this is by comparing with today
            today = TimePoint.today()
            for i in range(7):
                if (today + TimeAmount(f"-{i}d")).as_int() == date.as_int():
                    return work_done_values.get(i, TimeAmount("0p"))
            return TimeAmount("0p")

        self.statistics_service.getWorkDone.side_effect = mock_get_work_done

        # Set up getWorkloadStats to return predefined values
        workload_stats = (
            "2.0p",  # workload
            "10p",   # remaining effort
            "0.8",   # heuristic value
            "Urgency",  # heuristic name
            "Task 1",   # offender
            "1.5p"      # offenderMax
        )
        self.statistics_service.getWorkloadStats.return_value = workload_stats

        # Set up getWorkDoneLog to return a sample log
        work_done_log = [
            {"task": "Task 1", "work_units": "2", "timestamp": TimePoint.now().as_int()},
            {"task": "Task 2", "work_units": "1", "timestamp": TimePoint.now().as_int() - 3600}
        ]
        self.statistics_service.getWorkDoneLog.return_value = work_done_log

        # Act
        result = self.task_list_manager.get_list_stats()

        # Assert
        # Check that the result contains expected parts
        self.assertIn("Work done in the last 7 days:", result)
        self.assertIn("|    Date    | Work Done |", result)

        # Check for the average work done (2 + 3 + 1.5 + 0 + 2.5 + 1 + 4) / 7 = 2.0
        self.assertIn("|   Average  |    2.0    |", result)

        # Check workload statistics section
        self.assertIn("Workload statistics:", result)
        self.assertIn("current workload: 2.0p per day", result)
        self.assertIn("max Offender: 'Task 1' with 1.5p per day", result)
        self.assertIn("total remaining effort: 10p", result)
        self.assertIn("max Urgency: 0.8", result)

        # Check work done log section
        self.assertIn("Work done log:", result)
        for entry in work_done_log:
            task = entry["task"]
            work_units = entry["work_units"]
            timeAmount = TimeAmount(f"{work_units}p")
            self.assertIn(f"{timeAmount} on {task}", result)

        # Check navigation option is present
        self.assertIn("/list - return back to the task list", result)

        # Verify function calls
        self.assertEqual(self.statistics_service.getWorkDone.call_count, 7)
        self.statistics_service.getWorkloadStats.assert_called_once_with(self.task_list)
        self.statistics_service.getWorkDoneLog.assert_called_once()

    def test_get_list_stats_with_zero_work_done(self):
        # Arrange
        # Set up getWorkDone to always return zero
        self.statistics_service.getWorkDone.return_value = TimeAmount("0p")

        # Set up getWorkloadStats to return predefined values
        workload_stats = (
            "0p",    # workload
            "0p",    # remaining effort
            "0.0",   # heuristic value
            "Priority",  # heuristic name
            "None",  # offender
            "0p"     # offenderMax
        )
        self.statistics_service.getWorkloadStats.return_value = workload_stats

        # Set up empty work log
        self.statistics_service.getWorkDoneLog.return_value = []

        # Act
        result = self.task_list_manager.get_list_stats()

        # Assert
        # Check that the result contains expected parts
        self.assertIn("Work done in the last 7 days:", result)

        # Check for zero average work done
        self.assertIn("|   Average  |    0.0    |", result)

        # Check workload statistics section with zeros
        self.assertIn("current workload: 0p per day", result)
        self.assertIn("total remaining effort: 0p", result)

        # Check empty work done log section
        self.assertIn("Work done log:", result)

        # Verify function calls
        self.assertEqual(self.statistics_service.getWorkDone.call_count, 7)
        self.statistics_service.getWorkloadStats.assert_called_once()
        self.statistics_service.getWorkDoneLog.assert_called_once()


if __name__ == '__main__':
    unittest.main()
