import unittest
from src.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.SlackHeuristic import SlackHeuristic
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.JsonLoader import JsonLoader

class IntegrationTests(unittest.TestCase):
    def test_ObsidianTaskProviderIntegrationTest(self):
        # Arrange
        jsonLoader = JsonLoader()
        taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
        obsidianTaskProvider = ObsidianTaskProvider(taskJsonProvider)
        
        # Act
        taskList = obsidianTaskProvider.getTaskList()
        
        # Assert
        self.assertIsNotNone(taskList)

        # Print
        for task in taskList:
            print(task.getDescription() + "\r\n")

    def test_SlackHeuristicIntegrationTest(self):
        # Arrange
        jsonLoader = JsonLoader()
        taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
        obsidianTaskProvider = ObsidianTaskProvider(taskJsonProvider)
        taskList = obsidianTaskProvider.getTaskList()
        
        algorithm = SlackHeuristic(2.11)

        # Act
        sortedList = algorithm.sort(taskList)
        
        # Assert
        for i in range(1, len(sortedList)):
            self.assertTrue(sortedList[i-1][1] >= sortedList[i][1])

        # Print
        for task in sortedList:
            if task[1] > 0:
                print(task[0].getDescription() + " - " + str(task[1]) + "\r\n")

    def test_RemainingEffortIntegrationTest(self):
        # Arrange
        jsonLoader = JsonLoader()
        taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
        obsidianTaskProvider = ObsidianTaskProvider(taskJsonProvider)
        taskList = obsidianTaskProvider.getTaskList()
        
        algorithm = RemainingEffortHeuristic(2.11, 1.0)

        # Act
        sortedList = algorithm.sort(taskList)
        
        # Assert
        for i in range(1, len(sortedList)):
            self.assertTrue(sortedList[i-1][1] >= sortedList[i][1])

        # Print
        for task in sortedList:
            if task[1] > 0:
                print(task[0].getDescription() + " - " + str(task[1]) + "\r\n")

if __name__ == '__main__':
    unittest.main()