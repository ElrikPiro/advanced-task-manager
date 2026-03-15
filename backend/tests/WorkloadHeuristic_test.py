import unittest
from unittest.mock import MagicMock
from src.heuristics.WorkloadHeuristic import WorkloadHeuristic
from src.wrappers.TimeManagement import TimeAmount


class TestWorkloadHeuristic(unittest.TestCase):

    def setUp(self):
        self.heuristic = WorkloadHeuristic()

        # Create mock tasks
        # task1: getTotalCost() = TimeAmount("10p"), calculateRemainingTime() = TimeAmount("4d") -> expected = 10/4 = 2.5
        self.task1 = MagicMock()
        self.task1.getTotalCost.return_value = TimeAmount("10p")
        self.task1.calculateRemainingTime.return_value = TimeAmount("4d")

        # task2: getTotalCost() = TimeAmount("8p"), calculateRemainingTime() = TimeAmount("2d") -> expected = 8/2 = 4.0
        self.task2 = MagicMock()
        self.task2.getTotalCost.return_value = TimeAmount("8p")
        self.task2.calculateRemainingTime.return_value = TimeAmount("2d")

        # task3: getTotalCost() = TimeAmount("15p"), calculateRemainingTime() = TimeAmount("5d") -> expected = 15/5 = 3.0
        self.task3 = MagicMock()
        self.task3.getTotalCost.return_value = TimeAmount("15p")
        self.task3.calculateRemainingTime.return_value = TimeAmount("5d")

    def test_init(self):
        # Test that the constructor does not require parameters
        heuristic = WorkloadHeuristic()
        self.assertIsNotNone(heuristic)

    def test_evaluate(self):
        # Test the evaluation of a single task
        result = self.heuristic.evaluate(self.task1)

        # Manual calculation:
        # r = 10 (10 pomodoros)
        # d = 4 (4 days)
        # h = r/d = 10/4 = 2.5

        self.assertAlmostEqual(result, 2.5, places=2)

    def test_fast_evaluate(self):
        # Test the fast evaluation of a single task
        result = self.heuristic.fastEvaluate(self.task1)

        # Same calculation as evaluate
        self.assertAlmostEqual(result, 2.5, places=2)

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
        self.assertEqual(comment, "2.5")

    def test_critical_deadline(self):
        # Test when d < 1 (less than 1 day remaining)
        critical_task = MagicMock()
        critical_task.getTotalCost.return_value = TimeAmount("10p")
        critical_task.calculateRemainingTime.return_value = TimeAmount("0.5d")

        result = self.heuristic.evaluate(critical_task)
        self.assertEqual(result, 10)

    def test_division_by_zero(self):
        # Test when division by zero occurs
        zero_div_task = MagicMock()
        zero_div_task.getTotalCost.return_value = TimeAmount("0p")
        zero_div_task.calculateRemainingTime.return_value = TimeAmount("2d")

        result = self.heuristic.evaluate(zero_div_task)
        self.assertEqual(result, 0)

    def test_negative_result(self):
        # Test when we would get a negative result (h <= 0)
        negative_task = MagicMock()
        negative_task.getTotalCost.return_value = TimeAmount("0p")
        negative_task.calculateRemainingTime.return_value = TimeAmount("5d")

        result = self.heuristic.evaluate(negative_task)
        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
