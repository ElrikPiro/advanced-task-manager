import unittest
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.JsonLoader import JsonLoader

class ObsidianTaskProviderIntegrationTest(unittest.TestCase):
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

if __name__ == '__main__':
    unittest.main()