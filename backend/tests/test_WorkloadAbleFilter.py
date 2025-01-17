import unittest
from unittest.mock import MagicMock
from src.WorkloadAbleFilter import WorkloadAbleFilter
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.IFilter import IFilter

class WorkloadAbleFilterTests(unittest.TestCase):
    def setUp(self):
        self.activeFilter = MagicMock(spec=IFilter)
        self.filter = WorkloadAbleFilter(self.activeFilter)

    def test_filter_with_active_tasks(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task1.calculateRemainingTime.return_value = 2.0
        task2 = MagicMock(spec=ITaskModel)
        task2.calculateRemainingTime.return_value = 1.5
        tasks = [task1, task2]
        self.activeFilter.filter.return_value = tasks

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 2)
        self.assertEqual(filtered_tasks[0], task1)
        self.assertEqual(filtered_tasks[1], task2)

    def test_filter_with_inactive_tasks(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task1.calculateRemainingTime.return_value = 0.5
        task2 = MagicMock(spec=ITaskModel)
        task2.calculateRemainingTime.return_value = 0.8
        tasks = [task1, task2]
        self.activeFilter.filter.return_value = tasks

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 0)

if __name__ == '__main__':
    unittest.main()
