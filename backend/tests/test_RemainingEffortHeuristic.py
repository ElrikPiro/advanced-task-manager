import unittest
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.Interfaces.ITaskModel import ITaskModel
from unittest import TestCase, mock
from src.wrappers.TimeManagement import TimeAmount

class RemainingEffortHeuristicTests(TestCase):

    def test_sort(self):
        # Create mock tasks
        task1 = mock.Mock(spec=ITaskModel)
        task2 = mock.Mock(spec=ITaskModel)
        task3 = mock.Mock(spec=ITaskModel)
        tasks = [task1, task2, task3]

        # Create instance of SlackHeuristic
        heuristic = RemainingEffortHeuristic(5, 1)

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
        task.getTotalCost.return_value = TimeAmount("1h")
        task.getInvestedEffort.return_value = TimeAmount("0h")
        task.calculateRemainingTime.return_value = 2

        # Create instance of SlackHeuristic
        heuristic = RemainingEffortHeuristic(1, 1)

        # Call the evaluate method
        result = round(heuristic.evaluate(task), 2)

        # Assert the expected result
        self.assertEqual(result, 0)

if __name__ == '__main__':
    unittest.main()
