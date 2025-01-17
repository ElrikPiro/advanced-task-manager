import unittest
from unittest.mock import MagicMock
from src.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.ITaskProvider import ITaskProvider

class DaysToThresholdHeuristicTests(unittest.TestCase):
    def setUp(self):
        self.pomodorosPerDayProvider = MagicMock(spec=ITaskProvider)
        self.threshold = 1.0
        self.heuristic = DaysToThresholdHeuristic(self.pomodorosPerDayProvider, self.threshold)

    def test_sort(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task2 = MagicMock(spec=ITaskModel)
        task3 = MagicMock(spec=ITaskModel)
        tasks = [task1, task2, task3]

        self.pomodorosPerDayProvider.getTaskListAttribute.return_value = "5"
        self.heuristic.fastEvaluate = MagicMock(side_effect=[10, 5, 8])

        # Act
        sorted_tasks = self.heuristic.sort(tasks)

        # Assert
        self.assertEqual(sorted_tasks, [(task1, 10), (task3, 8), (task2, 5)])

    def test_evaluate(self):
        # Arrange
        task = MagicMock(spec=ITaskModel)
        task.getSeverity.return_value = 1
        task.getTotalCost.return_value = 1
        task.calculateRemainingTime.return_value = 2

        self.pomodorosPerDayProvider.getTaskListAttribute.return_value = "5"

        # Act
        result = self.heuristic.evaluate(task)

        # Assert
        self.assertAlmostEqual(result, 1.6, places=2)

if __name__ == '__main__':
    unittest.main()
