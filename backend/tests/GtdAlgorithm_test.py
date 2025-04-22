import unittest
from unittest.mock import Mock
from src.algorithms.GtdAlgorithm import GtdAlgorithm
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.IHeuristic import IHeuristic
from src.Interfaces.IFilter import IFilter
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestGtdAlgorithm(unittest.TestCase):
    def setUp(self):
        self.mock_filter = Mock(spec=IFilter)
        self.mock_heuristic = Mock(spec=IHeuristic)
        self.mock_task = Mock(spec=ITaskModel)
        self.mock_task.getDue.return_value = TimePoint(0)
        self.mock_task.getCalm.return_value = False

        self.algorithm = GtdAlgorithm(
            orderedCategories=[("Category1", self.mock_filter)],
            orderedHeuristics=[(self.mock_heuristic, 0.5)],
            defaultHeuristic=(self.mock_heuristic, 0.2)
        )

    def test_filter_urgents(self):
        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("-1d")  # Past due
        tasks = [self.mock_task]
        result = self.algorithm._filterUrgents(tasks)
        assert len(result) == 1

    def test_filter_ordered_categories(self):
        self.mock_filter.filter.return_value = [self.mock_task]
        tasks = [self.mock_task]
        result = self.algorithm._filterOrderedCategories(tasks)
        assert len(result) == 1
        self.mock_filter.filter.assert_called_once_with(tasks)

    def test_filter_by_heuristic(self):
        self.mock_heuristic.evaluate.return_value = 0.6  # Above threshold
        tasks = [self.mock_task]
        result = self.algorithm._filterByHeuristic(self.mock_heuristic, 0.5, tasks)
        assert len(result) == 1
        self.mock_heuristic.evaluate.assert_called_once_with(self.mock_task)

    def test_filter_calm_tasks(self):
        self.mock_task.getCalm.return_value = False  # Not calm
        tasks = [self.mock_task]
        result = self.algorithm._filterCalmTasks(tasks)
        assert len(result) == 1

    def test_apply_with_urgent_tasks(self):
        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("-1d")  # Past due
        self.mock_filter.filter.return_value = [self.mock_task]
        tasks = [self.mock_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1

    def test_apply_with_heuristic_tasks(self):
        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        self.mock_heuristic.evaluate.return_value = 0.6  # Above threshold
        self.mock_filter.filter.return_value = [self.mock_task]
        tasks = [self.mock_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1

    def test_apply_with_default_heuristic(self):
        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        self.mock_heuristic.evaluate.side_effect = [0.4, 0.3]  # Below thresholds
        self.mock_filter.filter.return_value = []
        tasks = [self.mock_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1


if __name__ == '__main__':
    unittest.main()
