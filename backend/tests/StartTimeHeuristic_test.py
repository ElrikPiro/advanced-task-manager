import unittest
from unittest.mock import MagicMock
from src.heuristics.StartTimeHeuristic import StartTimeHeuristic
from src.Interfaces.ITaskModel import ITaskModel


class TestStartTimeHeuristic(unittest.TestCase):
    def setUp(self):
        self.heuristic = StartTimeHeuristic()

    def test_sort(self):
        # Mock tasks
        task1 = MagicMock(spec=ITaskModel)
        task1.getStart.return_value.as_int.return_value = 2000
        task1.getStart.return_value.as_string.return_value = "2000"

        task2 = MagicMock(spec=ITaskModel)
        task2.getStart.return_value.as_int.return_value = 1000
        task2.getStart.return_value.as_string.return_value = "1000"

        tasks = [task1, task2]
        sorted_tasks = self.heuristic.sort(tasks)

        self.assertEqual(sorted_tasks[0][0], task2)
        self.assertEqual(sorted_tasks[1][0], task1)

    def test_evaluate(self):
        task = MagicMock(spec=ITaskModel)
        task.getStart.return_value.as_int.return_value = 1500

        score = self.heuristic.evaluate(task)
        self.assertEqual(score, 1.5)

    def test_getComment(self):
        task = MagicMock(spec=ITaskModel)
        task.getStart.return_value.as_string.return_value = "1500"

        comment = self.heuristic.getComment(task)
        self.assertEqual(comment, "1500")


if __name__ == "__main__":
    unittest.main()
