import unittest
from unittest.mock import Mock
from src.Interfaces.IHeuristic import IHeuristic
from src.algorithms.HeuristicAlgorithm import HeuristicAlgorithm
from src.Interfaces.ITaskModel import ITaskModel


class TestHeuristicAlgorithm(unittest.TestCase):
    def setUp(self):
        self.mock_task1 = Mock(spec=ITaskModel)
        self.mock_task2 = Mock(spec=ITaskModel)
        self.mock_task3 = Mock(spec=ITaskModel)

        self.mock_task1.getTotalCost.return_value.as_int.return_value = 5
        self.mock_task2.getTotalCost.return_value.as_int.return_value = 3
        self.mock_task3.getTotalCost.return_value.as_int.return_value = 1

        self.mock_heuristic = Mock(spec=IHeuristic)
        self.mock_heuristic.sort.return_value = [
            (self.mock_task3, 1.0),
            (self.mock_task2, 3.0),
            (self.mock_task1, 5.0),
        ]

        self.algorithm = HeuristicAlgorithm(self.mock_heuristic, "Heuristic Algorithm")

    def test_apply_sorts_tasks_using_heuristic(self):
        tasks = [self.mock_task1, self.mock_task2, self.mock_task3]
        result = self.algorithm.apply(tasks)
        self.assertEqual(result, [self.mock_task3, self.mock_task2, self.mock_task1])


if __name__ == '__main__':
    unittest.main()
