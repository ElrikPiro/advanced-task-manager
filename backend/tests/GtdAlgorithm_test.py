import datetime
import unittest
from unittest.mock import Mock
from src.algorithms.GtdAlgorithm import GtdAlgorithm
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.IHeuristic import IHeuristic
from src.Interfaces.IStatisticsService import IStatisticsService
from src.Interfaces.IFilter import IFilter
from src.Utils import WorkloadStats
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestGtdAlgorithm(unittest.TestCase):
    def setUp(self):
        self.mock_filter = Mock(spec=IFilter)
        self.mock_heuristic = Mock(spec=IHeuristic)
        self.mock_statistics_service = Mock(spec=IStatisticsService)
        self.mock_calm_heuristic = Mock(spec=IHeuristic)
        self.mock_task = Mock(spec=ITaskModel)
        self.mock_task.getDue.return_value = TimePoint(datetime.datetime.now())
        self.mock_task.getCalm.return_value = False

        self.algorithm = GtdAlgorithm(
            orderedCategories=[("Category1", self.mock_filter, True)],
            orderedHeuristics=[(self.mock_heuristic, 0.5)],
            defaultHeuristic=(self.mock_heuristic, 0.2),
            statisticService=self.mock_statistics_service,
            calmHeuristic=self.mock_calm_heuristic
        )

    def _make_workload_stats(self, workDone: dict[str, float] = None, workload_str: str = "4p"):
        """Helper to create a WorkloadStats with proper dict-based workDone."""
        if workDone is None:
            workDone = {}
        return WorkloadStats(
            workload=TimeAmount(workload_str),
            remainingEffort=TimeAmount("0p"),
            maxHeuristic=0.0,
            HeuristicName="",
            offender="",
            offenderMax=TimeAmount("0p"),
            workDone=workDone,
            workDoneLog=[]
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
        """Non-urgent task with heuristic above threshold should be returned via ordered heuristics."""
        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        self.mock_heuristic.evaluate.return_value = 0.6  # Above threshold
        self.mock_filter.filter.return_value = [self.mock_task]
        tasks = [self.mock_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1

    def test_apply_with_default_heuristic(self):
        """When ordered heuristics don't match, falls through to default heuristic
        if daily work objective is not yet fulfilled."""
        isoformatDate = datetime.datetime.now().date().isoformat()
        workStats = self._make_workload_stats(
            workDone={isoformatDate: 0.0},  # No work done yet
            workload_str="4p"               # Workload target: 4 pomodoros
        )
        self.mock_statistics_service.getWorkloadStats.return_value = workStats

        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        self.mock_heuristic.evaluate.side_effect = [0.4, 0.3]  # Below ordered threshold (0.5), above default (0.2)
        self.mock_filter.filter.return_value = []
        tasks = [self.mock_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1

    def test_apply_falls_back_to_calm_when_daily_objective_fulfilled(self):
        """When daily work objective is fulfilled, algorithm should fall back to calm tasks."""
        isoformatDate = datetime.datetime.now().date().isoformat()
        workStats = self._make_workload_stats(
            workDone={isoformatDate: 5.0},  # Already done 5 pomodoros
            workload_str="4p"               # Workload target: 4 pomodoros
        )
        self.mock_statistics_service.getWorkloadStats.return_value = workStats

        calm_task = Mock(spec=ITaskModel)
        calm_task.getCalm.return_value = True
        calm_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")

        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        self.mock_heuristic.evaluate.return_value = 0.4  # Below ordered threshold
        self.mock_filter.filter.return_value = []
        self.mock_calm_heuristic.sort.return_value = [(calm_task, 1.0)]

        tasks = [self.mock_task, calm_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1
        assert result[0] == calm_task
        assert "Daily objective fulfilled" in self.algorithm.getDescription()

    def test_apply_falls_back_to_calm_when_default_heuristic_returns_empty(self):
        """When default heuristic returns no tasks, algorithm should fall back to calm tasks."""
        isoformatDate = datetime.datetime.now().date().isoformat()
        workStats = self._make_workload_stats(
            workDone={isoformatDate: 0.0},  # No work done yet
            workload_str="4p"
        )
        self.mock_statistics_service.getWorkloadStats.return_value = workStats

        calm_task = Mock(spec=ITaskModel)
        calm_task.getCalm.return_value = True
        calm_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")

        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        # Below both ordered (0.5) and default (0.2) thresholds
        self.mock_heuristic.evaluate.return_value = 0.1
        self.mock_filter.filter.return_value = []
        self.mock_calm_heuristic.sort.return_value = [(calm_task, 1.0)]

        tasks = [self.mock_task, calm_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1
        assert result[0] == calm_task
        assert "Daily objective fulfilled" in self.algorithm.getDescription()

    def test_apply_workDone_missing_date_defaults_to_zero(self):
        """When today's date is not in workDone dict, it should default to 0.0
        and continue with default heuristic (not fall back to calm)."""
        workStats = self._make_workload_stats(
            workDone={},       # No entries at all
            workload_str="4p"
        )
        self.mock_statistics_service.getWorkloadStats.return_value = workStats

        self.mock_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")  # Not urgent
        # Below ordered threshold (0.5), above default threshold (0.2)
        self.mock_heuristic.evaluate.side_effect = [0.4, 0.3]
        self.mock_filter.filter.return_value = []

        tasks = [self.mock_task]
        result = self.algorithm.apply(tasks)
        assert len(result) == 1

    def test_use_calm_instead(self):
        """use_calm_instead should return calm tasks sorted by calm heuristic."""
        calm_task1 = Mock(spec=ITaskModel)
        calm_task1.getCalm.return_value = True
        calm_task2 = Mock(spec=ITaskModel)
        calm_task2.getCalm.return_value = True
        non_calm_task = Mock(spec=ITaskModel)
        non_calm_task.getCalm.return_value = False

        self.mock_calm_heuristic.sort.return_value = [(calm_task2, 2.0), (calm_task1, 1.0)]

        result = self.algorithm.use_calm_instead([non_calm_task, calm_task1, calm_task2])
        assert len(result) == 2
        assert result[0] == calm_task2
        assert result[1] == calm_task1
        assert "Daily objective fulfilled" in self.algorithm.getDescription()
        assert self.mock_calm_heuristic.__class__.__name__ in self.algorithm.getDescription()

    def test_use_calm_instead_description(self):
        """use_calm_instead should set description mentioning daily objective fulfilled."""
        calm_task = Mock(spec=ITaskModel)
        calm_task.getCalm.return_value = True

        self.mock_calm_heuristic.sort.return_value = [(calm_task, 1.0)]

        self.algorithm.use_calm_instead([calm_task])
        description = self.algorithm.getDescription()
        assert "Daily objective fulfilled, falling back to" in description

    def test_apply_uses_non_calm_tasks_for_heuristics(self):
        """Ordered heuristics should only operate on non-calm tasks."""
        calm_task = Mock(spec=ITaskModel)
        calm_task.getCalm.return_value = True
        calm_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")

        non_calm_task = Mock(spec=ITaskModel)
        non_calm_task.getCalm.return_value = False
        non_calm_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")

        self.mock_heuristic.evaluate.return_value = 0.6  # Above threshold
        self.mock_filter.filter.return_value = [non_calm_task]

        tasks = [calm_task, non_calm_task]
        result = self.algorithm.apply(tasks)
        # Only the non-calm task should pass through
        assert len(result) == 1
        assert result[0] == non_calm_task

    def test_apply_uses_non_calm_tasks_for_workload_stats(self):
        """getWorkloadStats should receive only non-calm tasks."""
        isoformatDate = datetime.datetime.now().date().isoformat()
        workStats = self._make_workload_stats(
            workDone={isoformatDate: 0.0},
            workload_str="4p"
        )
        self.mock_statistics_service.getWorkloadStats.return_value = workStats

        calm_task = Mock(spec=ITaskModel)
        calm_task.getCalm.return_value = True
        calm_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")

        non_calm_task = Mock(spec=ITaskModel)
        non_calm_task.getCalm.return_value = False
        non_calm_task.getDue.return_value = TimePoint.today() + TimeAmount("1d")

        # Below ordered threshold, above default
        self.mock_heuristic.evaluate.side_effect = [0.4, 0.3]
        self.mock_filter.filter.return_value = []

        tasks = [calm_task, non_calm_task]
        self.algorithm.apply(tasks)

        # Verify getWorkloadStats was called with only non-calm tasks
        call_args = self.mock_statistics_service.getWorkloadStats.call_args
        assert len(call_args[0][0]) == 1
        assert call_args[0][0][0] == non_calm_task


if __name__ == '__main__':
    unittest.main()
