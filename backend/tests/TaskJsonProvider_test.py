import unittest
from unittest.mock import MagicMock, patch

from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry


class TestTaskJsonProvider(unittest.TestCase):
    def setUp(self):
        self.mock_file_broker = MagicMock(spec=IFileBroker)
        self.provider = TaskJsonProvider(self.mock_file_broker)

    def test_getJson_calls_file_broker(self):
        """Test that getJson calls the readFileContentJson method on the fileBroker with the correct parameters."""
        # Arrange
        mock_json = {"tasks": [], "projects": []}
        self.mock_file_broker.readFileContentJson.return_value = mock_json

        # Act
        result = self.provider.getJson()

        # Assert
        self.mock_file_broker.readFileContentJson.assert_called_once_with(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(result, mock_json)

    def test_getJson_injects_tasks_for_open_projects(self):
        """Test that getJson injects tasks for open projects without tasks."""
        # Arrange
        mock_json = {
            "tasks": [],
            "projects": [
                {"name": "Project1", "status": "open"},
                {"name": "Project2", "status": "closed"}
            ]
        }
        self.mock_file_broker.readFileContentJson.return_value = mock_json

        # Mock TimePoint.today() to return a fixed date
        with patch('src.wrappers.TimeManagement.TimePoint.today') as mock_today:
            mock_time_point = MagicMock()
            mock_time_point.as_int.return_value = 20230101
            mock_today.return_value = mock_time_point

            # Act
            result = self.provider.getJson()

            # Assert
            tasks = result.get("tasks", [])
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["project"], "Project1")
            self.assertEqual(tasks[0]["description"], "Define next action")
            self.assertEqual(tasks[0]["status"], " ")
            self.assertEqual(tasks[0]["context"], "alert")
            self.assertEqual(tasks[0]["start"], "20230101")
            self.assertEqual(tasks[0]["due"], "20230101")

    def test_getJson_with_existing_tasks(self):
        """Test that getJson doesn't duplicate tasks for projects that already have active tasks."""
        # Arrange
        mock_json = {
            "tasks": [
                {"description": "Task1", "project": "Project1", "status": " "}
            ],
            "projects": [
                {"name": "Project1", "status": "open"},
                {"name": "Project2", "status": "open"}
            ]
        }
        self.mock_file_broker.readFileContentJson.return_value = mock_json

        # Mock TimePoint.today() to return a fixed date
        with patch('src.wrappers.TimeManagement.TimePoint.today') as mock_today:
            mock_time_point = MagicMock()
            mock_time_point.as_int.return_value = 20230101
            mock_today.return_value = mock_time_point

            # Act
            result = self.provider.getJson()

            # Assert
            tasks = result.get("tasks", [])
            self.assertEqual(len(tasks), 2)  # Original task + injected task for Project2
            projects_with_tasks = set(task["project"] for task in tasks)
            self.assertEqual(projects_with_tasks, {"Project1", "Project2"})

    def test_getJson_with_completed_tasks(self):
        """Test that getJson considers the status of tasks when determining if a project needs a task."""
        # Arrange
        mock_json = {
            "tasks": [
                {"description": "CompletedTask", "project": "Project1", "status": "x"}
            ],
            "projects": [
                {"name": "Project1", "status": "open"}
            ]
        }
        self.mock_file_broker.readFileContentJson.return_value = mock_json

        # Mock TimePoint.today() to return a fixed date
        with patch('src.wrappers.TimeManagement.TimePoint.today') as mock_today:
            mock_time_point = MagicMock()
            mock_time_point.as_int.return_value = 20230101
            mock_today.return_value = mock_time_point

            # Act
            result = self.provider.getJson()

            # Assert
            tasks = result.get("tasks", [])
            self.assertEqual(len(tasks), 2)  # Original completed task + new injected task
            active_tasks = [task for task in tasks if task["status"] == " "]
            self.assertEqual(len(active_tasks), 1)
            self.assertEqual(active_tasks[0]["project"], "Project1")

    def test_getJson_empty(self):
        """Test getJson with empty JSON input."""
        # Arrange
        mock_json = {}
        self.mock_file_broker.readFileContentJson.return_value = mock_json

        # Act
        result = self.provider.getJson()

        # Assert
        self.assertEqual(result, {})  # No tasks or projects should be added if they don't exist

    def test_saveJson(self):
        """Test that saveJson calls the writeFileContentJson method on the fileBroker with the correct parameters."""
        # Arrange
        mock_json = {"tasks": [], "projects": []}

        # Act
        self.provider.saveJson(mock_json)

        # Assert
        self.mock_file_broker.writeFileContentJson.assert_called_once_with(FileRegistry.STANDALONE_TASKS_JSON, mock_json)


if __name__ == "__main__":
    unittest.main()
