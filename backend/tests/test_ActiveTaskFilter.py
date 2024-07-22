import unittest
from datetime import datetime, timedelta
from src.ActiveTaskFilter import ActiveTaskFilter
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.ITaskModel import ITaskModel

class ActiveTaskFilterTests(unittest.TestCase):
    def test_filter(self):
        # Arrange
        filter = ActiveTaskFilter()
        tomorrow = datetime.today() + timedelta(days=1)
        tasks = [
            MockTaskModel(1, tomorrow),  # Active task
            MockTaskModel(2, tomorrow),  # Active task
            MockTaskModel(3, datetime(2022, 1, 1)),  # Inactive task
            MockTaskModel(4, datetime(2022, 1, 1)),  # Inactive task
        ]

        # Act
        filtered_tasks = filter.filter(tasks)

        # Assert
        self.assertEqual(len(filtered_tasks), 2)

class MockTaskModel(ITaskModel):
    def __init__(self, task_id, start_time):
        self.task_id = task_id
        self.start_time = start_time

    def getStart(self):
        return self.start_time.timestamp() * 1000

    def __eq__(self, other):
        # Implement the __eq__ method here
        pass

    def calculateRemainingTime(self):
        # Implement the calculateRemainingTime method here
        pass

    def getContext(self):
        # Implement the getContext method here
        pass

    def getDescription(self):
        # Implement the getDescription method here
        pass

    def getDue(self):
        # Implement the getDue method here
        pass

    def getInvestedEffort(self):
        # Implement the getInvestedEffort method here
        pass

    def getSeverity(self):
        # Implement the getSeverity method here
        pass

    def getStatus(self):
        # Implement the getStatus method here
        pass

    def getTotalCost(self):
        # Implement the getTotalCost method here
        pass

    def setContext(self, context):
        # Implement the setContext method here
        pass

    def setDescription(self, description):
        # Implement the setDescription method here
        pass

    def setDue(self, due):
        # Implement the setDue method here
        pass

    def setInvestedEffort(self, invested_effort):
        # Implement the setInvestedEffort method here
        pass

    def setSeverity(self, severity):
        # Implement the setSeverity method here
        pass

    def setStart(self, start):
        # Implement the setStart method here
        pass

    def setStatus(self, status):
        # Implement the setStatus method here
        pass

    def setTotalCost(self, total_cost):
        # Implement the setTotalCost method here
        pass

if __name__ == '__main__':
    unittest.main()