import unittest
from unittest.mock import MagicMock
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.wrappers.TimeManagement import TimeAmount


class TestRemainingEffortHeuristic(unittest.TestCase):

    def setUp(self):
        self.dedication = TimeAmount("4p")  # 4 pomodoros per day
        self.desiredH = 1.5  # Desired heuristic value
        self.heuristic = RemainingEffortHeuristic(self.dedication, self.desiredH)

        # Create mock tasks
        self.task1 = MagicMock()
        self.task1.getSeverity.return_value = 2
        self.task1.getTotalCost.return_value = TimeAmount("10p")
        self.task1.calculateRemainingTime.return_value = TimeAmount("2d")

        self.task2 = MagicMock()
        self.task2.getSeverity.return_value = 1
        self.task2.getTotalCost.return_value = TimeAmount("8p")
        self.task2.calculateRemainingTime.return_value = TimeAmount("1d")

        self.task3 = MagicMock()
        self.task3.getSeverity.return_value = 3
        self.task3.getTotalCost.return_value = TimeAmount("15p")
        self.task3.calculateRemainingTime.return_value = TimeAmount("3d")

    def test_init(self):
        # Test that the constructor properly sets attributes
        self.assertEqual(self.heuristic.dedication, self.dedication)
        self.assertEqual(self.heuristic.desiredH, self.desiredH)

    def test_evaluate(self):
        # Test the evaluation of a single task
        result = self.heuristic.evaluate(self.task1)

        # Manual calculation:
        # p = 4, w = 1, s = 2, r = 10, d = 2, dr = 1.5
        # r - ((dr * d * p) / (p * s * w + dr))
        # 10 - ((1.5 * 2 * 4) / (4 * 2 * 1 + 1.5))
        # 10 - (12 / 9.5) ≈ 8.74

        self.assertAlmostEqual(result, 8.74, places=2)

    def test_fast_evaluate(self):
        # Test the fast evaluation with explicitly provided pomodoros per day
        result = self.heuristic.fastEvaluate(self.task1, 4.0)

        self.assertAlmostEqual(result, 8.74, places=2)

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

        # The comment should be a string representation of the TimeAmount
        self.assertEqual(comment, "3h38m25.263s (8.76 pomodoros)")

    def test_different_dedication_values(self):
        # Test with different dedication values
        heuristic2 = RemainingEffortHeuristic(TimeAmount("2p"), self.desiredH)
        result = heuristic2.evaluate(self.task1)

        # Recalculation with p = 2
        # 10 - ((1.5 * 2 * 2) / (2 * 2 * 1 + 1.5)) ≈ 8.91

        self.assertAlmostEqual(result, 8.91, places=2)

    def test_different_desired_h_values(self):
        # Test with different desiredH values
        heuristic3 = RemainingEffortHeuristic(self.dedication, 3.0)
        result = heuristic3.evaluate(self.task1)

        # Recalculation with dr = 3
        # 10 - ((3 * 2 * 4) / (4 * 2 * 1 + 3)) ≈ 7.82

        self.assertAlmostEqual(result, 7.82, places=2)

    def test_extreme_values(self):
        # Test with extreme values
        extreme_task = MagicMock()
        extreme_task.getSeverity.return_value = 10  # Very high severity
        extreme_task.getTotalCost.return_value = TimeAmount("100p")  # Very high cost
        extreme_task.calculateRemainingTime.return_value = TimeAmount("0.1d")  # Very little time

        result = self.heuristic.evaluate(extreme_task)

        # The formula should still produce a meaningful result
        self.assertTrue(isinstance(result, float))
        # The result should be less than the total cost
        self.assertLessEqual(result, 100)


if __name__ == '__main__':
    unittest.main()
