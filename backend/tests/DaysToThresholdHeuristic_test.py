import unittest
from unittest.mock import MagicMock
from math import ceil
from src.heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestDaysToThresholdHeuristic(unittest.TestCase):

    def setUp(self):
        # Create a heuristic with dedication of 4 pomodoros per day and threshold of 7 days
        self.dedication = TimeAmount("4p")
        self.threshold = 7.0
        self.heuristic = DaysToThresholdHeuristic(self.dedication, self.threshold)

        # Create mock tasks with different properties
        self.today = TimePoint.today()

        # Setup base task mock with common methods
        def create_task_mock(remaining_days, cost, severity=1.0):
            task = MagicMock()
            task.calculateRemainingTime.return_value = TimeAmount(f"{remaining_days}d")
            task.getTotalCost.return_value = TimeAmount(f"{cost}p")
            task.getSeverity.return_value = severity
            return task

        # Task with low priority (far from threshold)
        self.low_priority_task = create_task_mock(20, 10, 1.0)

        # Task with medium priority (close to threshold)
        self.medium_priority_task = create_task_mock(10, 8, 1.0)

        # Task with high priority (at threshold)
        self.high_priority_task = create_task_mock(7, 5, 1.0)

        # Task with highest priority (beyond threshold)
        self.highest_priority_task = create_task_mock(3, 6, 1.0)

        # Task with high severity
        self.high_severity_task = create_task_mock(15, 10, 2.0)

        # Task with low cost
        self.low_cost_task = create_task_mock(7, 2, 1.0)

    def test_initialization(self):
        # Test initialization with different values
        heuristic1 = DaysToThresholdHeuristic(TimeAmount("2p"), 5.0)
        heuristic2 = DaysToThresholdHeuristic(TimeAmount("8p"), 14.0)

        # Verify the parameters are stored correctly
        self.assertEqual(self.heuristic.dedication.as_pomodoros(), 4.0)
        self.assertEqual(self.heuristic.threshold, 7.0)
        self.assertEqual(heuristic1.dedication.as_pomodoros(), 2.0)
        self.assertEqual(heuristic1.threshold, 5.0)
        self.assertEqual(heuristic2.dedication.as_pomodoros(), 8.0)
        self.assertEqual(heuristic2.threshold, 14.0)

    def test_fastEvaluate(self):
        # Test the scoring algorithm with different tasks
        pomodoros_per_day = 4.0

        # Calculate expected results
        # The formula is: d - (r * (p * s * w + h)) / (h * p)
        # where d = days remaining, r = total cost, p = pomodoros per day,
        # s = severity, w = 1, h = threshold

        # Low priority task: d=20, r=10, p=4, s=1, w=1, h=7
        # 20 - (10 * (4*1*1 + 7)) / (7*4) = 20 - 110/28 ≈ 16.07
        low_score = self.heuristic.fastEvaluate(self.low_priority_task, pomodoros_per_day)
        expected_low = 20 - (10 * (4 * 1 * 1 + 7)) / (7 * 4)
        self.assertAlmostEqual(low_score, expected_low, places=5)

        # High priority task: d=7, r=5, p=4, s=1, w=1, h=7
        # 7 - (5 * (4*1*1 + 7)) / (7*4) = 7 - 55/28 ≈ 5.04
        high_score = self.heuristic.fastEvaluate(self.high_priority_task, pomodoros_per_day)
        expected_high = 7 - (5 * (4 * 1 * 1 + 7)) / (7 * 4)
        self.assertAlmostEqual(high_score, expected_high, places=5)

        # Highest priority task: d=3, r=6, p=4, s=1, w=1, h=7
        # 3 - (6 * (4*1*1 + 7)) / (7*4) = 3 - 66/28 ≈ 0.64
        highest_score = self.heuristic.fastEvaluate(self.highest_priority_task, pomodoros_per_day)
        expected_highest = 3 - (6 * (4 * 1 * 1 + 7)) / (7 * 4)
        self.assertAlmostEqual(highest_score, expected_highest, places=5)

        # High severity task: d=15, r=10, p=4, s=2, w=1, h=7
        # 15 - (10 * (4*2*1 + 7)) / (7*4) = 15 - 150/28 ≈ 9.64
        severity_score = self.heuristic.fastEvaluate(self.high_severity_task, pomodoros_per_day)
        expected_severity = 15 - (10 * (4 * 2 * 1 + 7)) / (7 * 4)
        self.assertAlmostEqual(severity_score, expected_severity, places=5)

    def test_evaluate(self):
        # Test that evaluate uses the dedication from the heuristic

        # Mock task and calculate expected value
        task = MagicMock()
        task.calculateRemainingTime.return_value = TimeAmount("10d")
        task.getTotalCost.return_value = TimeAmount("7p")
        task.getSeverity.return_value = 1.5

        # Expected: d=10, r=7, p=4, s=1.5, w=1, h=7
        # 10 - (7 * (4*1.5*1 + 7)) / (7*4) = 10 - 91/28 ≈ 6.75
        expected = 10 - (7 * (4 * 1.5 * 1 + 7)) / (7 * 4)

        # Get actual result
        result = self.heuristic.evaluate(task)

        # Verify result
        self.assertAlmostEqual(result, expected, places=5)

    def test_sort(self):
        # Create a list of tasks in unsorted order
        tasks = [
            self.low_priority_task,
            self.medium_priority_task,
            self.high_priority_task,
            self.highest_priority_task
        ]

        # Sort using the heuristic
        sorted_tasks = self.heuristic.sort(tasks)

        # Verify the tasks are sorted by their scores in descending order
        # (higher score = higher priority)
        self.assertEqual(len(sorted_tasks), 4)

        # Extract scores for verification
        scores = [score for _, score in sorted_tasks]

        # Verify scores are in descending order
        self.assertTrue(all(scores[i] < scores[i + 1] for i in range(len(scores) - 1)))

        # The highest priority task should come first
        self.assertEqual(sorted_tasks[0][0], self.highest_priority_task)

        # The low priority task should come last
        self.assertEqual(sorted_tasks[-1][0], self.low_priority_task)

    def test_sort_with_empty_list(self):
        # Test sorting an empty task list
        result = self.heuristic.sort([])
        self.assertEqual(result, [])

    def test_sort_with_equal_scores(self):
        # Create two tasks with identical parameters
        task1 = MagicMock()
        task1.calculateRemainingTime.return_value = TimeAmount("5d")
        task1.getTotalCost.return_value = TimeAmount("3p")
        task1.getSeverity.return_value = 1.0

        task2 = MagicMock()
        task2.calculateRemainingTime.return_value = TimeAmount("5d")
        task2.getTotalCost.return_value = TimeAmount("3p")
        task2.getSeverity.return_value = 1.0

        # Sort the tasks
        result = self.heuristic.sort([task1, task2])

        # Both should have the same score
        self.assertEqual(result[0][1], result[1][1])

    def test_getComment(self):
        # Test the comment generation for different tasks

        # For low priority task (expected days ~16.07, ceil to 17)
        low_comment = self.heuristic.getComment(self.low_priority_task)
        self.assertEqual(low_comment, "17 days")

        # For high priority task (expected days ~5.04, ceil to 6)
        high_comment = self.heuristic.getComment(self.high_priority_task)
        self.assertEqual(high_comment, "6 days")

        # For highest priority task (expected days ~0.64, ceil to 1)
        highest_comment = self.heuristic.getComment(self.highest_priority_task)
        self.assertEqual(highest_comment, "1 days")

        # Test with a task that evaluates to negative days
        negative_task = MagicMock()
        negative_task.calculateRemainingTime.return_value = TimeAmount("1d")
        negative_task.getTotalCost.return_value = TimeAmount("20p")
        negative_task.getSeverity.return_value = 3.0

        # Formula should yield a negative result, but ceil will bring it to at least 0
        negative_comment = self.heuristic.getComment(negative_task)
        self.assertEqual(negative_comment, "-12 days")

    def test_with_extreme_values(self):
        # Test with extreme task values
        extreme_task = MagicMock()
        extreme_task.calculateRemainingTime.return_value = TimeAmount("100d")
        extreme_task.getTotalCost.return_value = TimeAmount("100p")
        extreme_task.getSeverity.return_value = 10.0

        # Calculate expected score
        # d=100, r=100, p=4, s=10, w=1, h=7
        # 100 - (100 * (4*10*1 + 7)) / (7*4) = 100 - 4700/28 ≈ -67.86
        expected = 100 - (100 * (4 * 10 * 1 + 7)) / (7 * 4)

        # Evaluate and verify
        result = self.heuristic.evaluate(extreme_task)
        self.assertAlmostEqual(result, expected, places=5)

        # Test comment (ceil of negative number is rounded up to nearest integer <= the value)
        comment = self.heuristic.getComment(extreme_task)
        self.assertEqual(comment, f"{ceil(expected)} days")


if __name__ == '__main__':
    unittest.main()
