import unittest
from unittest.mock import MagicMock
from src.GtdTaskFilter import GtdTaskFilter
from src.Interfaces.IFilter import IFilter
from src.Interfaces.IHeuristic import IHeuristic
from src.Interfaces.ITaskModel import ITaskModel

class GtdTaskFilterTests(unittest.TestCase):
    def setUp(self):
        self.activeFilter = MagicMock(spec=IFilter)
        self.orderedCategories = [("Category 1", MagicMock(spec=IFilter)), ("Category 2", MagicMock(spec=IFilter))]
        self.orderedHeuristics = [(MagicMock(spec=IHeuristic), 1.0), (MagicMock(spec=IHeuristic), 2.0)]
        self.defaultHeuristic = (MagicMock(spec=IHeuristic), 0.5)
        self.filter = GtdTaskFilter(self.activeFilter, self.orderedCategories, self.orderedHeuristics, self.defaultHeuristic)

    def test_filter_with_urgent_tasks(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task1.getDue.return_value = 0
        task2 = MagicMock(spec=ITaskModel)
        task2.getDue.return_value = 0
        tasks = [task1, task2]
        self.activeFilter.filter.return_value = tasks

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 2)
        self.assertEqual(filtered_tasks[0], task1)
        self.assertEqual(filtered_tasks[1], task2)

    def test_filter_with_non_urgent_tasks(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task1.getDue.return_value = 9999999999999
        task2 = MagicMock(spec=ITaskModel)
        task2.getDue.return_value = 9999999999999
        tasks = [task1, task2]
        self.activeFilter.filter.return_value = tasks

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 0)

    def test_filter_with_heuristic_tasks(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task2 = MagicMock(spec=ITaskModel)
        tasks = [task1, task2]
        self.activeFilter.filter.return_value = tasks
        self.orderedHeuristics[0][0].evaluate.side_effect = [1.5, 2.5]

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 2)
        self.assertEqual(filtered_tasks[0], task2)
        self.assertEqual(filtered_tasks[1], task1)

    def test_filter_with_default_heuristic(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task2 = MagicMock(spec=ITaskModel)
        tasks = [task1, task2]
        self.activeFilter.filter.return_value = tasks
        self.orderedHeuristics[0][0].evaluate.side_effect = [0.5, 0.5]
        self.defaultHeuristic[0].evaluate.side_effect = [0.6, 0.4]

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 2)
        self.assertEqual(filtered_tasks[0], task1)
        self.assertEqual(filtered_tasks[1], task2)

if __name__ == '__main__':
    unittest.main()
