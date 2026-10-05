import unittest
from unittest.mock import MagicMock, patch

from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError


class TestTaskJsonProvider(unittest.TestCase):
    def setUp(self):
        self.mock_file_broker = MagicMock(spec=IFileBroker)
        self.identity_path = "/configured/tasks.json"
        self.mock_file_broker.getFilePath.return_value = self.identity_path
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

    def test_getJson_is_pure_for_open_projects_without_tasks(self):
        """A normal read must not reconcile or persist a project's next action."""
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
            self.assertEqual(result, mock_json)
            self.mock_file_broker.writeFileContentJson.assert_not_called()

    def test_discover_persists_tasks_for_open_projects_without_active_tasks(self):
        mock_json = {
            "tasks": [],
            "projects": [
                {"name": "Project1", "status": "open"},
                {"name": "Project2", "status": "closed"}
            ]
        }
        self.mock_file_broker.readFileContentJson.return_value = mock_json

        with patch('src.wrappers.TimeManagement.TimePoint.today') as mock_today:
            mock_time_point = MagicMock()
            mock_time_point.as_int.return_value = 20230101
            mock_today.return_value = mock_time_point

            result = self.provider.discover()

        tasks = result["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["project"], "Project1")
        self.assertEqual(tasks[0]["description"], "Define next action")
        self.assertEqual(tasks[0]["status"], " ")
        self.assertEqual(tasks[0]["context"], "alert")
        self.assertEqual(tasks[0]["start"], "20230101")
        self.assertEqual(tasks[0]["due"], "20230101")
        self.assertEqual(tasks[0]["id"], fallback_task_id("Define next action", self.identity_path, 0))
        self.mock_file_broker.writeFileContentJson.assert_called_once_with(FileRegistry.STANDALONE_TASKS_JSON, result)

    def test_discover_with_existing_tasks(self):
        """Discovery only adds actions for open projects without active tasks."""
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
            result = self.provider.discover()

            # Assert
            tasks = result.get("tasks", [])
            self.assertEqual(len(tasks), 2)  # Original task + injected task for Project2
            projects_with_tasks = set(task["project"] for task in tasks)
            self.assertEqual(projects_with_tasks, {"Project1", "Project2"})

    def test_discover_with_completed_tasks(self):
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
            result = self.provider.discover()

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

    def test_getJson_rejects_invalid_declared_ids(self):
        self.mock_file_broker.readFileContentJson.return_value = {"tasks": [{"description": "Bad", "id": " \t"}]}

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()

    def test_saveJson_rejects_invalid_declared_ids_before_writing(self):
        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.saveJson({"tasks": [{"description": "Bad", "id": 42}]})

        self.mock_file_broker.writeFileContentJson.assert_not_called()

    def test_discover_does_not_create_a_task_with_a_conflicting_id(self):
        conflicting_id = fallback_task_id("Define next action", self.identity_path, 1)
        self.mock_file_broker.readFileContentJson.return_value = {
            "tasks": [{"description": "Finished", "project": "Other", "status": "x", "id": conflicting_id}],
            "projects": [{"name": "Project1", "status": "open"}],
        }

        with self.assertRaisesRegex(AmbiguousTaskIdentityError, "conflicts with an existing task"):
            self.provider.discover()

        self.mock_file_broker.writeFileContentJson.assert_not_called()


if __name__ == "__main__":
    unittest.main()
