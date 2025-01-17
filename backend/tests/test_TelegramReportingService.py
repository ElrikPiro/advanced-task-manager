import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from src.TelegramReportingService import TelegramReportingService
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.IUserCommService import IUserCommService
from src.Interfaces.ITaskProvider import ITaskProvider
from src.Interfaces.IScheduling import IScheduling
from src.Interfaces.IStatisticsService import IStatisticsService
from src.Interfaces.IHeuristic import IHeuristic
from src.Interfaces.IFilter import IFilter

class TelegramReportingServiceTests(unittest.TestCase):
    def setUp(self):
        self.bot = MagicMock(spec=IUserCommService)
        self.taskProvider = MagicMock(spec=ITaskProvider)
        self.scheduling = MagicMock(spec=IScheduling)
        self.statisticsProvider = MagicMock(spec=IStatisticsService)
        self.heuristics = [("Heuristic1", MagicMock(spec=IHeuristic))]
        self.filters = [("Filter1", MagicMock(spec=IFilter))]
        self.categories = [{"prefix": "work"}]
        self.chatId = 123456789
        self.reportingService = TelegramReportingService(self.bot, self.taskProvider, self.scheduling, self.statisticsProvider, self.heuristics, self.filters, self.categories, self.chatId)

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

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_processMessage_SendsTaskList_WhenMessageTextIsList(self, mock_sendTaskList):
        # Arrange
        message = "/list"
        self.taskProvider.getTaskList.return_value = ['Task 1', 'Task 2']
        self.reportingService._lastTaskList = ['Task 1', 'Task 2']

        # Act
        self.reportingService.processMessage(message)

        # Assert
        mock_sendTaskList.assert_called_once()

    def test_processMessage_Exits_WhenMessageTextIsExit(self):
        # Arrange
        message = "/exit"
        
        # Act
        self.reportingService.processMessage(message)
        
        # Assert
        self.assertFalse(self.reportingService.run)

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_sendTaskList_DoesNotShowExtraPage_WhenTasksEqualTasksPerPage(self, mock_sendTaskList):
        # Arrange
        self.reportingService._lastTaskList = ['Task 1', 'Task 2', 'Task 3', 'Task 4', 'Task 5']
        self.reportingService._tasksPerPage = 5

        # Act
        self.reportingService._taskListPage = 0
        self.reportingService.sendTaskList()

        # Assert
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskInformation', new_callable=AsyncMock)
    def test_selectTaskCommand_SendsTaskInformation(self, mock_sendTaskInformation):
        # Arrange
        self.reportingService._lastTaskList = [MagicMock(spec=ITaskModel) for _ in range(10)]
        self.reportingService._tasksPerPage = 5
        message = "/task_3"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        mock_sendTaskInformation.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskInformation', new_callable=AsyncMock)
    def test_taskInfoCommand_SendsTaskInformation(self, mock_sendTaskInformation):
        # Arrange
        self.reportingService._selectedTask = MagicMock(spec=ITaskModel)
        message = "/info"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        mock_sendTaskInformation.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendHelp', new_callable=AsyncMock)
    def test_helpCommand_SendsHelp(self, mock_sendHelp):
        # Arrange
        message = "/help"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        mock_sendHelp.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_heuristicSelectionCommand_UpdatesHeuristicAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        message = "/heuristic_1"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.assertEqual(self.reportingService._selectedHeuristicIndex, 0)
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_filterSelectionCommand_UpdatesFilterAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        message = "/filter_1"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.assertEqual(self.reportingService._selectedFilterIndex, 0)
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_doneCommand_MarksTaskAsDoneAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        self.reportingService._selectedTask = MagicMock(spec=ITaskModel)
        message = "/done"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.reportingService._selectedTask.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(self.reportingService._selectedTask)
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskInformation', new_callable=AsyncMock)
    def test_setCommand_UpdatesTaskParameterAndSendsTaskInformation(self, mock_sendTaskInformation):
        # Arrange
        self.reportingService._selectedTask = MagicMock(spec=ITaskModel)
        message = "/set description New Description"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.reportingService._selectedTask.setDescription.assert_called_once_with("New Description")
        self.taskProvider.saveTask.assert_called_once_with(self.reportingService._selectedTask)
        mock_sendTaskInformation.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskInformation', new_callable=AsyncMock)
    def test_newCommand_CreatesNewTaskAndSendsTaskInformation(self, mock_sendTaskInformation):
        # Arrange
        message = "/new New Task"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("New Task")
        self.taskProvider.saveTask.assert_called_once()
        mock_sendTaskInformation.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskInformation', new_callable=AsyncMock)
    def test_scheduleCommand_SchedulesTaskAndSendsTaskInformation(self, mock_sendTaskInformation):
        # Arrange
        self.reportingService._selectedTask = MagicMock(spec=ITaskModel)
        message = "/schedule"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.scheduling.schedule.assert_called_once_with(self.reportingService._selectedTask, "")
        self.taskProvider.saveTask.assert_called_once_with(self.reportingService._selectedTask)
        mock_sendTaskInformation.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskInformation', new_callable=AsyncMock)
    def test_workCommand_InvestsWorkInTaskAndSendsTaskInformation(self, mock_sendTaskInformation):
        # Arrange
        self.reportingService._selectedTask = MagicMock(spec=ITaskModel)
        message = "/work 2"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.reportingService._selectedTask.setInvestedEffort.assert_called_once()
        self.taskProvider.saveTask.assert_called_once_with(self.reportingService._selectedTask)
        self.statisticsProvider.doWork.assert_called_once()
        mock_sendTaskInformation.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_snoozeCommand_SnoozesTaskAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        self.reportingService._selectedTask = MagicMock(spec=ITaskModel)
        message = "/snooze"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.reportingService._selectedTask.setStart.assert_called_once()
        self.taskProvider.saveTask.assert_called_once_with(self.reportingService._selectedTask)
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_exportCommand_ExportsTasksAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        message = "/export json"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.taskProvider.exportTasks.assert_called_once_with("json")
        self.bot.sendFile.assert_called_once()
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_importCommand_ImportsTasksAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        message = "/import json"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        self.taskProvider.importTasks.assert_called_once_with("json")
        self.taskProvider.getTaskList.assert_called_once()
        self.bot.sendMessage.assert_called_once()
        mock_sendTaskList.assert_called_once()

    @patch('src.TelegramReportingService.TelegramReportingService.sendTaskList', new_callable=AsyncMock)
    def test_searchCommand_FindsTasksAndSendsTaskList(self, mock_sendTaskList):
        # Arrange
        self.reportingService._lastRawList = [MagicMock(spec=ITaskModel) for _ in range(10)]
        self.reportingService._lastRawList[0].getDescription.return_value = "Task 1"
        self.reportingService._lastRawList[1].getDescription.return_value = "Task 2"
        message = "/search Task 1"

        # Act
        self.reportingService.processMessage(message)

        # Assert
        mock_sendTaskList.assert_called_once()

if __name__ == '__main__':
    unittest.main()
