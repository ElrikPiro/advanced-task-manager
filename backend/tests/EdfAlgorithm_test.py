import unittest
from unittest.mock import Mock
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.Interfaces.ITaskModel import ITaskModel
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestEdfAlgorithm(unittest.TestCase):
    def setUp(self):
        self.mock_task1 = Mock(spec=ITaskModel)
        self.mock_task2 = Mock(spec=ITaskModel)
        self.mock_task3 = Mock(spec=ITaskModel)

        self.mock_task1.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Due in 1 day
        self.mock_task2.getDue.return_value = TimePoint.today() + TimeAmount("2d")
        self.mock_task3.getDue.return_value = TimePoint.today() + TimeAmount("3d")

        self.algorithm = EdfAlgorithm()

    def test_apply_sorts_tasks_by_due_date(self):
        tasks = [self.mock_task3, self.mock_task1, self.mock_task2]
        result = self.algorithm.apply(tasks)
        self.assertEqual(result, [self.mock_task1, self.mock_task2, self.mock_task3])


if __name__ == '__main__':
    unittest.main()
