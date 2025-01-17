import unittest
from unittest.mock import MagicMock
from src.HeuristicScheduling import HeuristicScheduling
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.ITaskProvider import ITaskProvider

class HeuristicSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.pomodoroConstProvider = MagicMock(spec=ITaskProvider)
        self.scheduling = HeuristicScheduling(self.pomodoroConstProvider)

    def test_schedule_with_effort_per_day(self):
        # Arrange
        task = MagicMock(spec=ITaskModel)
        task.calculateRemainingTime.return_value = 10
        task.getTotalCost.return_value = 5
        self.pomodoroConstProvider.getTaskListAttribute.return_value = "5"

        # Act
        self.scheduling.schedule(task, "2")

        # Assert
        task.setDue.assert_called_once()
        task.setSeverity.assert_called_once_with(0.5)

    def test_schedule_without_effort_per_day(self):
        # Arrange
        task = MagicMock(spec=ITaskModel)
        task.calculateRemainingTime.return_value = 10
        task.getTotalCost.return_value = 5
        self.pomodoroConstProvider.getTaskListAttribute.return_value = "5"

        # Act
        self.scheduling.schedule(task, "")

        # Assert
        task.setSeverity.assert_called_once_with(1.0)

if __name__ == '__main__':
    unittest.main()
