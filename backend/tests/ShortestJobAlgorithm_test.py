import unittest
from unittest.mock import Mock
from src.algorithms.ShortestJobAlgorithm import ShortestJobAlgorithm
from src.Interfaces.ITaskModel import ITaskModel


class TestShortestJobAlgorithm(unittest.TestCase):
    def setUp(self):
        self.mock_task1 = Mock(spec=ITaskModel)
        self.mock_task2 = Mock(spec=ITaskModel)
        self.mock_task3 = Mock(spec=ITaskModel)

        self.mock_task1.getTotalCost.return_value.as_pomodoros.return_value = 5  # Cost of 5
        self.mock_task2.getTotalCost.return_value.as_pomodoros.return_value = 3  # Cost of 3
        self.mock_task3.getTotalCost.return_value.as_pomodoros.return_value = 1  # Cost of 1

        self.algorithm = ShortestJobAlgorithm()

    def test_apply_sorts_tasks_by_execution_time(self):
        tasks = [self.mock_task1, self.mock_task2, self.mock_task3]
        result = self.algorithm.apply(tasks)
        self.assertEqual(result, [self.mock_task3, self.mock_task2, self.mock_task1])

    def test_apply_updates_description(self):
        tasks = [self.mock_task1, self.mock_task2, self.mock_task3]
        self.algorithm.apply(tasks)
        description = self.algorithm.getDescription()
        self.assertIn("Shortest Job First (SJF) Algorithm", description)
        self.assertIn("3 tasks sorted by execution time", description)

    def test_apply_with_empty_task_list(self):
        tasks = []
        result = self.algorithm.apply(tasks)
        self.assertEqual(result, [])
        description = self.algorithm.getDescription()
        self.assertIn("Shortest Job First (SJF) Algorithm", description)
        self.assertIn("0 tasks sorted by execution time", description)


if __name__ == '__main__':
    unittest.main()
