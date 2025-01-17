import unittest
from src.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.Interfaces.ITaskModel import ITaskModel
from unittest.mock import MagicMock

class ContextPrefixTaskFilterTests(unittest.TestCase):
    def setUp(self):
        self.prefilter = MagicMock()
        self.prefix = "test"
        self.filter = ContextPrefixTaskFilter(self.prefilter, self.prefix)

    def test_filter_with_prefilter(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task1.getContext.return_value = "test_context"
        task2 = MagicMock(spec=ITaskModel)
        task2.getContext.return_value = "other_context"
        tasks = [task1, task2]
        self.prefilter.filter.return_value = tasks

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 1)
        self.assertEqual(filtered_tasks[0], task1)

    def test_filter_without_prefilter(self):
        # Arrange
        self.filter = ContextPrefixTaskFilter(None, self.prefix)
        task1 = MagicMock(spec=ITaskModel)
        task1.getContext.return_value = "test_context"
        task2 = MagicMock(spec=ITaskModel)
        task2.getContext.return_value = "other_context"
        tasks = [task1, task2]

        # Act
        filtered_tasks = self.filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 1)
        self.assertEqual(filtered_tasks[0], task1)

if __name__ == '__main__':
    unittest.main()
