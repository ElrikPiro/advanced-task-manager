import unittest
from datetime import datetime, timedelta
from src.SlackHeuristic import SlackHeuristic
from src.Interfaces.ITaskModel import ITaskModel
from unittest import TestCase, mock
from datetime import datetime, timedelta
from src.SlackHeuristic import SlackHeuristic
from src.Interfaces.ITaskModel import ITaskModel

class SlackHeuristicTests(TestCase):

    def test_sort(self):
        # Create mock tasks
        task1 = mock.Mock(spec=ITaskModel)
        task2 = mock.Mock(spec=ITaskModel)
        task3 = mock.Mock(spec=ITaskModel)
        tasks = [task1, task2, task3]

        # Create instance of SlackHeuristic
        heuristic = SlackHeuristic(5)

        # Mock the evaluate method
        heuristic.evaluate = mock.Mock(side_effect=[10, 5, 8])

        # Call the sort method
        sorted_tasks = heuristic.sort(tasks)

        # Assert the expected sorting order
        self.assertEqual(sorted_tasks, [(task1, 10), (task3, 8), (task2, 5)])

    def test_evaluate(self):
        # Create mock task
        task = mock.Mock(spec=ITaskModel)
        task.getSeverity.return_value = 1
        task.getTotalCost.return_value = 1
        task.getInvestedEffort.return_value = 0
        task.calculateRemainingTime.return_value = 2

        # Create instance of SlackHeuristic
        heuristic = SlackHeuristic(1)

        # Call the evaluate method
        result = round(heuristic.evaluate(task), 2)

        # Assert the expected result
        self.assertEqual(result, 1)

    def test_fastEvaluate(self):
        # Create mock task
        task = mock.Mock(spec=ITaskModel)
        task.getSeverity.return_value = 1
        task.getTotalCost.return_value = 1
        task.getInvestedEffort.return_value = 0
        task.calculateRemainingTime.return_value = 2

        # Create instance of SlackHeuristic
        heuristic = SlackHeuristic(1)

        # Call the fastEvaluate method
        result = round(heuristic.fastEvaluate(task, 1), 2)

        # Assert the expected result
        self.assertEqual(result, 1)

if __name__ == '__main__':
    unittest.main()
