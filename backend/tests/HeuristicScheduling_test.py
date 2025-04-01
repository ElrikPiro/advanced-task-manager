import unittest
from unittest.mock import MagicMock
from src.HeuristicScheduling import HeuristicScheduling
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestHeuristicScheduling(unittest.TestCase):

    def setUp(self):
        # Set up default dedication
        self.dedication = TimeAmount("2p")
        self.scheduler = HeuristicScheduling(self.dedication)

        # Create mock task
        self.task = MagicMock()
        self.task.calculateRemainingTime.return_value = TimeAmount("5d")
        self.task.getTotalCost.return_value = TimeAmount("10p")
        self.start_time = TimePoint.today()
        self.task.getStart.return_value = self.start_time

    def test_initialization(self):
        # Test initialization with different TimeAmount values
        dedication1 = TimeAmount("1p")
        dedication2 = TimeAmount("4h")

        scheduler1 = HeuristicScheduling(dedication1)
        scheduler2 = HeuristicScheduling(dedication2)

        # No explicit assertions needed since we're just testing that initialization doesn't fail
        self.assertIsNotNone(scheduler1)
        self.assertIsNotNone(scheduler2)

    def test_schedule_with_integer_param(self):
        # Arrange
        param = "2"

        # Act
        self.scheduler.schedule(self.task, param)

        # Assert
        # When param = 2, severity should be 1/2 = 0.5
        # With r = 10, p = 2, severity = 0.5
        # optimalDayTo = ceil((10 * (2 * 0.5 + 1)) / 2) = ceil(10) = 10
        expected_severity = 0.5
        expected_days = 10

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_called_once()
        # Check that due date is start_time + expected_days days
        due_date_arg = self.task.setDue.call_args[0][0]
        self.assertEqual(due_date_arg.as_int(), (self.start_time + TimeAmount(f"{expected_days}d")).as_int())

    def test_schedule_with_decimal_param(self):
        # Arrange
        param = "0.5"

        # Act
        self.scheduler.schedule(self.task, param)

        # Assert
        # When param = 0.5, severity should be 1/0.5 = 2.0
        # With r = 10, p = 2, severity = 2.0
        # optimalDayTo = ceil((10 * (2 * 2.0 + 1)) / 2) = ceil(25) = 25
        expected_severity = 2.0
        expected_days = 25

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_called_once()
        due_date_arg = self.task.setDue.call_args[0][0]
        self.assertEqual(due_date_arg.as_int(), (self.start_time + TimeAmount(f"{expected_days}d")).as_int())

    def test_schedule_with_small_numeric_param(self):
        # Arrange
        param = "0.1"

        # Act
        self.scheduler.schedule(self.task, param)

        # Assert
        # When param = 0.1, severity should be 1/0.1 = 10.0
        # optimalDayTo = ceil((10 * (2 * 10.0 + 1)) / 2) = ceil(105) = 105
        expected_severity = 10.0
        expected_days = 105

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_called_once()
        due_date_arg = self.task.setDue.call_args[0][0]
        self.assertEqual(due_date_arg.as_int(), (self.start_time + TimeAmount(f"{expected_days}d")).as_int())

    def test_schedule_with_non_numeric_param(self):
        # Arrange
        param = "auto"

        # Act
        self.scheduler.schedule(self.task, param)

        # Assert
        # With d = 5, p = 2, r = 10
        # severity = max((5 * 2 - 10) / (2 * 10), 1) = max(0, 1) = 1
        expected_severity = 1.0

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_not_called()  # Due date should not be set in this case

    def test_schedule_with_non_numeric_param_calculated_severity(self):
        # Arrange
        param = "auto"
        self.task.calculateRemainingTime.return_value = TimeAmount("10d")

        # Act
        self.scheduler.schedule(self.task, param)

        # Assert
        # With d = 10, p = 2, r = 10
        # severity = max((10 * 2 - 10) / (2 * 10), 1) = max(1, 1) = 1
        expected_severity = 1.0

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_not_called()

    def test_schedule_with_non_numeric_param_higher_severity(self):
        # Arrange
        param = "auto"
        self.task.calculateRemainingTime.return_value = TimeAmount("25d")

        # Act
        self.scheduler.schedule(self.task, param)

        # Assert
        # With d = 15, p = 2, r = 10
        # severity = max((25 * 2 - 10) / (2 * 10), 1) = max(2, 1) = 2
        expected_severity = 2.0

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
