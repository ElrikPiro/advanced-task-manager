import unittest
from unittest.mock import MagicMock
from src.heuristics.SlackHeuristic import SlackHeuristic
from src.wrappers.TimeManagement import TimeAmount


class TestSlackHeuristic(unittest.TestCase):

    def setUp(self):
        self.dedication = TimeAmount("4p")  # 4 pomodoros per day
        self.daysOffset = 0
        self.heuristic = SlackHeuristic(self.dedication, self.daysOffset)

        # Create mock tasks
        self.task1 = MagicMock()
        self.task1.getSeverity.return_value = 2
        self.task1.getTotalCost.return_value = TimeAmount("10p")
        self.task1.calculateRemainingTime.return_value = TimeAmount("4d")

        self.task2 = MagicMock()
        self.task2.getSeverity.return_value = 1
        self.task2.getTotalCost.return_value = TimeAmount("8p")
        self.task2.calculateRemainingTime.return_value = TimeAmount("3d")

        self.task3 = MagicMock()
        self.task3.getSeverity.return_value = 3
        self.task3.getTotalCost.return_value = TimeAmount("15p")
        self.task3.calculateRemainingTime.return_value = TimeAmount("5d")

    def test_init(self):
        # Test that the constructor properly sets attributes
        self.assertEqual(self.heuristic.dedication, self.dedication)
        self.assertEqual(self.heuristic.daysOffset, self.daysOffset)

    def test_evaluate(self):
        # Test the evaluation of a single task
        result = self.heuristic.evaluate(self.task1)

        # Manual calculation:
        # p = 4, w = 1, s = 2, r = 10, d = 4
        # (p * w * s * r) / (p * d - r)
        # (4 * 1 * 2 * 10) / (4 * 4 - 10)
        # 80 / 6 ≈ 13.33

        self.assertAlmostEqual(result, 13.33, places=2)

    def test_fast_evaluate(self):
        # Test the fast evaluation with explicitly provided pomodoros per day
        result = self.heuristic.fastEvaluate(self.task1, 4.0)

        self.assertAlmostEqual(result, 13.33, places=2)

    def test_sort(self):
        # Test sorting of tasks based on evaluations
        tasks = [self.task1, self.task2, self.task3]
        sorted_tasks = self.heuristic.sort(tasks)

        # Check that we get a list of tuples (task, value)
        self.assertEqual(len(sorted_tasks), 3)
        self.assertTrue(all(isinstance(item, tuple) and len(item) == 2 for item in sorted_tasks))

        # Check sorting order (highest evaluation first)
        self.assertTrue(sorted_tasks[0][1] >= sorted_tasks[1][1] >= sorted_tasks[2][1])

        # Verify that all tasks are present
        task_objects = [item[0] for item in sorted_tasks]
        self.assertIn(self.task1, task_objects)
        self.assertIn(self.task2, task_objects)
        self.assertIn(self.task3, task_objects)

    def test_get_comment(self):
        # Test the generation of comment string
        comment = self.heuristic.getComment(self.task1)
        self.assertEqual(comment, "13.33")

    def test_different_dedication_values(self):
        # Test with different dedication values
        heuristic2 = SlackHeuristic(TimeAmount("2p"), self.daysOffset)
        result = heuristic2.evaluate(self.task1)

        # Recalculation with p = 2
        # (2 * 1 * 2 * 10) / (2 * 4 - 10)
        # 40 / (8 - 10) = 40 / -2 = -20 (negative, so should return 100)

        self.assertEqual(result, 100)

    def test_different_days_offset(self):
        # Test with different daysOffset values
        heuristic3 = SlackHeuristic(self.dedication, 1)

        # This changes d from 4 to 3
        result = heuristic3.evaluate(self.task1)

        # Recalculation with d = 3
        # (4 * 1 * 2 * 10) / (4 * 3 - 10)
        # 80 / 2 = 40

        self.assertEqual(result, 40.0)

    def test_critical_deadline(self):
        # Test when d < 1
        critical_task = MagicMock()
        critical_task.getSeverity.return_value = 2
        critical_task.getTotalCost.return_value = TimeAmount("10p")
        critical_task.calculateRemainingTime.return_value = TimeAmount("0.5d")

        result = self.heuristic.evaluate(critical_task)
        self.assertEqual(result, 100)

    def test_division_by_zero(self):
        # Test when p*d = r (which would cause division by zero)
        zero_div_task = MagicMock()
        zero_div_task.getSeverity.return_value = 2
        zero_div_task.getTotalCost.return_value = TimeAmount("12p")
        zero_div_task.calculateRemainingTime.return_value = TimeAmount("3d")

        # With p=4, d=3, r=12 we get: p*d - r = 4*3 - 12 = 0
        result = self.heuristic.evaluate(zero_div_task)
        self.assertEqual(result, 100)

    def test_negative_result(self):
        # Test when we would get a negative result (when p*d < r)
        negative_task = MagicMock()
        negative_task.getSeverity.return_value = 2
        negative_task.getTotalCost.return_value = TimeAmount("20p")
        negative_task.calculateRemainingTime.return_value = TimeAmount("4d")

        # With p=4, d=4, r=20 we get: p*d - r = 4*4 - 20 = -4
        # Which would give a negative h, but the method should return 100
        result = self.heuristic.evaluate(negative_task)
        self.assertEqual(result, 100)


if __name__ == '__main__':
    unittest.main()
