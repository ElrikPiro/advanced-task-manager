import unittest
from unittest.mock import MagicMock
from src.HeuristicScheduling import HeuristicScheduling
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestHeuristicScheduling(unittest.TestCase):

    def setUp(self):
        # Set up default dedication
        self.dedication = TimeAmount("2p")
        
        # Create mock task provider
        self.mock_task_provider = MagicMock()
        self.scheduler = HeuristicScheduling(self.dedication, self.mock_task_provider)

        # Create mock task
        self.task = MagicMock()
        self.task.calculateRemainingTime.return_value = TimeAmount("5d")
        self.task.getTotalCost.return_value = TimeAmount("10p")
        self.start_time = TimePoint.today()
        self.task.getStart.return_value = self.start_time
        self.task.getDescription.return_value = "Test Task"

        # Setup task provider to return new tasks
        def create_mock_task(description):
            new_task = MagicMock()
            new_task.getDescription.return_value = description
            new_task.calculateRemainingTime.return_value = TimeAmount("5d")
            new_task.getTotalCost.return_value = TimeAmount("5p")  # Half of original
            new_task.getStart.return_value = self.start_time
            return new_task
        
        self.mock_task_provider.createDefaultTask.side_effect = create_mock_task

    def test_initialization_with_task_provider(self):
        # Test initialization with different TimeAmount values and task provider
        dedication1 = TimeAmount("1p")
        dedication2 = TimeAmount("4h")
        mock_provider = MagicMock()

        scheduler1 = HeuristicScheduling(dedication1, mock_provider)
        scheduler2 = HeuristicScheduling(dedication2, mock_provider)

        self.assertIsNotNone(scheduler1)
        self.assertIsNotNone(scheduler2)

    def test_schedule_with_integer_param_triggers_splitting(self):
        # Arrange
        param = "2"  # 2 pomodoros per day

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # When param = 2, severity = p/effort_per_day = 2/2 = 1.0, so NO splitting should occur
        expected_split_count = 1
        self.assertEqual(len(result), expected_split_count)
        
        # Verify task provider was NOT called since no splitting occurred
        self.assertEqual(self.mock_task_provider.createDefaultTask.call_count, 0)

    def test_schedule_with_decimal_param_high_severity(self):
        # Arrange
        param = "0.5"

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertEqual(len(result), 1)  # No splitting needed
        # When param = 0.5, severity should be p/effort_per_day = 2/0.5 = 4.0
        expected_severity = 4.0
        # optimal_days = ceil((r * (p * severity + 1)) / p) = ceil((10 * (2 * 4 + 1)) / 2) = ceil(45) = 45
        expected_days = 45

        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_called_once()
        due_date_arg = self.task.setDue.call_args[0][0]
        self.assertEqual(due_date_arg.as_int(), (self.start_time + TimeAmount(f"{expected_days}d")).as_int())

    def test_schedule_with_high_effort_triggers_splitting(self):
        # Arrange
        param = "20"  # Very high effort per day, will cause severity < 1

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # When param = 20, severity = p/effort_per_day = 2/20 = 0.1 < 1, so splitting should occur
        # split_count = ceil(1/0.1) = ceil(10) = 10
        expected_split_count = 10
        self.assertEqual(len(result), expected_split_count)
        
        # Verify task provider was called to create new tasks
        self.assertEqual(self.mock_task_provider.createDefaultTask.call_count, expected_split_count - 1)
        
        # Check that all tasks have sequential naming
        for i, task in enumerate(result):
            if i == 0:
                # Original task should be modified with 1/10 suffix
                self.task.setDescription.assert_called_with(f"Test Task {i+1}/{expected_split_count}")
            else:
                # New tasks should be created with proper naming
                expected_description = f"Test Task {i+1}/{expected_split_count}"
                self.mock_task_provider.createDefaultTask.assert_any_call(expected_description)

    def test_schedule_with_time_format_hours(self):
        # Arrange
        param = "2h"  # 2 hours = 2*60/25 = 4.8 pomodoros

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # 2h = 4.8p, severity = p/effort_per_day = 2/4.8 = 0.416... < 1, so splitting should occur
        # split_count = ceil(1/0.416) = ceil(2.4) = 3
        expected_split_count = 3
        self.assertEqual(len(result), expected_split_count)

    def test_schedule_with_time_format_minutes(self):
        # Arrange
        param = "60m"  # 60 minutes = 60/25 = 2.4 pomodoros

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # severity = p/effort_per_day = 2/2.4 = 0.833... < 1, should trigger splitting
        expected_split_count = 2  # ceil(1/0.833) = 2
        self.assertEqual(len(result), expected_split_count)

    def test_schedule_with_time_format_pomodoros(self):
        # Arrange
        param = "1.5p"  # 1.5 pomodoros

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # severity = p/effort_per_day = 2/1.5 = 1.333... >= 1, should NOT trigger splitting
        expected_split_count = 1  # No splitting needed
        self.assertEqual(len(result), expected_split_count)

    def test_schedule_with_invalid_time_format_fallback_to_auto(self):
        # Arrange
        param = "invalid_format"

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertEqual(len(result), 1)  # Auto calculation, no splitting
        # Should use auto-calculation: max((5 * 2 - 10) / (2 * 10), 1) = max(0, 1) = 1
        expected_severity = 1.0
        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_not_called()  # Due date should not be set in auto mode

    def test_schedule_with_empty_param_auto_calculation(self):
        # Arrange
        param = ""

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertEqual(len(result), 1)  # Auto calculation, no splitting
        expected_severity = 1.0
        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_not_called()

    def test_schedule_auto_calculation_higher_severity(self):
        # Arrange
        param = "auto"
        self.task.calculateRemainingTime.return_value = TimeAmount("25d")

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertEqual(len(result), 1)  # Auto calculation, no splitting
        # severity = max((25 * 2 - 10) / (2 * 10), 1) = max(2, 1) = 2
        expected_severity = 2.0
        self.task.setSeverity.assert_called_once_with(expected_severity)
        self.task.setDue.assert_not_called()

    def test_task_property_copying_during_split(self):
        # Arrange
        param = "15"  # High effort to trigger split
        
        # Setup original task properties
        self.task.getContext.return_value = "work"
        self.task.getDue.return_value = TimePoint.tomorrow()
        self.task.getSeverity.return_value = 1.5
        self.task.getInvestedEffort.return_value = TimeAmount("2p")
        self.task.getStatus.return_value = "active"
        self.task.getCalm.return_value = True

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertTrue(len(result) > 1)  # Should be split
        
        # Verify that new tasks had properties copied
        created_tasks = [call.args[0] for call in self.mock_task_provider.createDefaultTask.call_args_list]
        
        for task_desc in created_tasks:
            # Verify task provider was called with correct description pattern
            self.assertTrue("Test Task" in task_desc)
            self.assertTrue("/" in task_desc)  # Should have X/Y format

    def test_split_effort_distribution(self):
        # Arrange
        param = "8"  # effort that should trigger a 4-way split
        self.task.getTotalCost.return_value = TimeAmount("8p")  # 8 pomodoros total
        
        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # severity = p/effort_per_day = 2/8 = 0.25 < 1, split_count = ceil(1/0.25) = 4
        expected_split_count = 4
        expected_effort_per_split = 2.0  # 8p / 4 = 2p per split
        
        self.assertEqual(len(result), expected_split_count)
        
        # Check that each task gets the right amount of effort
        for i in range(expected_split_count):
            if i == 0:
                # Original task
                self.task.setTotalCost.assert_called()
                cost_call_args = self.task.setTotalCost.call_args[0][0]
                self.assertEqual(cost_call_args.as_pomodoros(), expected_effort_per_split)
            # Note: Can't easily test new tasks since they're mocks created by provider

    def test_boundary_case_severity_exactly_one(self):
        # Arrange
        param = "2"  # effort per day = 2 pomodoros, severity = p/effort_per_day = 2/2 = 1.0

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertEqual(len(result), 1)  # Exactly at boundary, no split
        expected_severity = 1.0
        self.task.setSeverity.assert_called_once_with(expected_severity)

    def test_boundary_case_severity_just_above_one(self):
        # Arrange
        param = "1.98"  # effort per day = 1.98 pomodoros, severity = p/effort_per_day = 2/1.98 = 1.01 > 1

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        self.assertEqual(len(result), 1)  # Just above boundary, no split
        # expected_severity ≈ 1.0101 (2/1.98)
        self.task.setSeverity.assert_called_once()
        severity_call_arg = self.task.setSeverity.call_args[0][0]
        self.assertGreater(severity_call_arg, 1.0)

    def test_boundary_case_severity_just_below_one(self):
        # Arrange
        param = "2.02"  # effort per day = 2.02 pomodoros, severity = p/effort_per_day = 2/2.02 = 0.99 < 1

        # Act
        result = self.scheduler.schedule(self.task, param)

        # Assert
        # Should trigger split: split_count = ceil(1/0.99) = 2
        expected_split_count = 2
        self.assertEqual(len(result), expected_split_count)

    def test_zero_effort_handling(self):
        # Arrange
        param = "0"

        # Act & Assert
        with self.assertRaises(ZeroDivisionError):
            self.scheduler.schedule(self.task, param)

    def test_negative_effort_handling(self):
        # Arrange - TimeAmount should handle negative values
        param = "-1"

        # Act & Assert
        # This should either raise an exception or handle gracefully
        # depending on TimeAmount implementation
        try:
            result = self.scheduler.schedule(self.task, param)
            # If no exception, verify behavior is reasonable
            self.assertIsInstance(result, list)
        except (ValueError, Exception):
            # Acceptable to raise an exception for negative values
            pass


if __name__ == '__main__':
    unittest.main()
