import unittest
from unittest.mock import MagicMock
from datetime import datetime, date
from src.StatisticsService import StatisticsService
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry
from src.Interfaces.IFilter import IFilter
from src.Interfaces.IHeuristic import IHeuristic

class StatisticsServiceTests(unittest.TestCase):
    def setUp(self):
        self.fileBroker = MagicMock(spec=IFileBroker)
        self.workLoadAbleFilter = MagicMock(spec=IFilter)
        self.remainingEffortHeuristic = MagicMock(spec=IHeuristic)
        self.mainHeuristic = MagicMock(spec=IHeuristic)
        self.statisticsService = StatisticsService(self.fileBroker, self.workLoadAbleFilter, self.remainingEffortHeuristic, self.mainHeuristic)

    def test_initialize(self):
        # Arrange
        self.fileBroker.readFileContentJson.return_value = {"2022-01-01": 5.0}

        # Act
        self.statisticsService.initialize()

        # Assert
        self.assertEqual(self.statisticsService.workDone, {"2022-01-01": 5.0})

    def test_doWork(self):
        # Arrange
        self.statisticsService.workDone = {"2022-01-01": 5.0}
        work_date = date(2022, 1, 2)
        work_units = 3.0

        # Act
        self.statisticsService.doWork(work_date, work_units)

        # Assert
        self.assertEqual(self.statisticsService.workDone, {"2022-01-01": 5.0, "2022-01-02": 3.0})
        self.fileBroker.writeFileContentJson.assert_called_once_with(FileRegistry.STATISTICS_JSON, {"2022-01-01": 5.0, "2022-01-02": 3.0})

    def test_getWorkDone(self):
        # Arrange
        self.statisticsService.workDone = {"2022-01-01": 5.0}
        work_date = date(2022, 1, 1)

        # Act
        result = self.statisticsService.getWorkDone(work_date)

        # Assert
        self.assertEqual(result, 5.0)

    def test_getWorkloadStats(self):
        # Arrange
        task1 = MagicMock(spec=ITaskModel)
        task2 = MagicMock(spec=ITaskModel)
        taskList = [task1, task2]
        self.workLoadAbleFilter.filter.return_value = taskList
        self.remainingEffortHeuristic.evaluate.side_effect = [2.0, 3.0]
        self.mainHeuristic.evaluate.side_effect = [1.0, 4.0]
        task1.getTotalCost.return_value = 5.0
        task2.getTotalCost.return_value = 6.0
        task1.calculateRemainingTime.return_value = 2.0
        task2.calculateRemainingTime.return_value = 3.0
        task1.getDescription.return_value = "Task 1"
        task2.getDescription.return_value = "Task 2"

        # Act
        result = self.statisticsService.getWorkloadStats(taskList)

        # Assert
        self.assertEqual(result, [3.4, 5.0, 4.0, self.mainHeuristic.__class__.__name__, "Task 2", 2.0])

if __name__ == '__main__':
    unittest.main()
