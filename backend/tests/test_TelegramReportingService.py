import unittest
from unittest.mock import MagicMock
from src.TelegramReportingService import TelegramReportingService

class TelegramReportingServiceTests(unittest.TestCase):
    def setUp(self):
        self.bot = MagicMock()
        self.taskProvider = MagicMock()
        self.chatId = 123456789
        self.reportingService = TelegramReportingService(self.bot, self.taskProvider, self.chatId)

    def test_wasListUpdated_ReturnsTrue_WhenListIsUpdated(self):
        # Arrange
        self.taskProvider.getTaskList.return_value = ['Task 1', 'Task 2']
        self.reportingService._lastTaskList = ['Task 1']
        
        # Act
        result = self.reportingService.pullListUpdates()
        
        # Assert
        self.assertTrue(result)

    def test_wasListUpdated_ReturnsFalse_WhenListIsNotUpdated(self):
        # Arrange
        self.taskProvider.getTaskList.return_value = ['Task 1', 'Task 2']
        self.reportingService._lastTaskList = ['Task 1', 'Task 2']
        
        # Act
        result = self.reportingService.pullListUpdates()
        
        # Assert
        self.assertFalse(result)

    def test_processMessage_SendsTaskList_WhenMessageTextIsList(self):
        # Arrange
        message = MagicMock()
        message.text = "/list"
        self.taskProvider.getTaskList.return_value = ['Task 1', 'Task 2']
        self.reportingService._lastTaskList = ['Task 1', 'Task 2']

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.bot.sendMessage.assert_called_with(chat_id=self.chatId, text="Task 1\nTask 2\n\nPage 1 of 1")

    def test_processMessage_Exits_WhenMessageTextIsExit(self):
        # Arrange
        message = MagicMock()
        message.text = "/exit"
        
        # Act
        self.reportingService.processMessage(message)
        
        # Assert
        self.assertFalse(self.reportingService.run)

    def test_sendTaskList_DoesNotShowExtraPage_WhenTasksEqualTasksPerPage(self):
        # Arrange
        self.reportingService._lastTaskList = ['Task 1', 'Task 2', 'Task 3', 'Task 4', 'Task 5']
        self.reportingService._tasksPerPage = 5

        # Act
        self.reportingService._taskListPage = 0
        self.reportingService.sendTaskList()

        # Assert
        self.bot.sendMessage.assert_called_with(chat_id=self.chatId, text="Task 1\nTask 2\nTask 3\nTask 4\nTask 5\n\nPage 1 of 1\n/next - Next page\n/previous - Previous page\n\nselected /heuristic : \nselected /filter : ")

if __name__ == '__main__':
    unittest.main()
