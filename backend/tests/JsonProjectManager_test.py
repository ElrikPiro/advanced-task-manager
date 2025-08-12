import unittest
from unittest.mock import MagicMock

from src.JsonProjectManager import JsonProjectManager
from src.Interfaces.IProjectManager import ProjectCommands
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider


class TestJsonProjectManager(unittest.TestCase):
    def setUp(self):
        self.mock_provider = MagicMock(spec=ITaskJsonProvider)
        self.project_manager = JsonProjectManager(self.mock_provider)

        # Setup common test data
        self.test_projects = [
            {
                "name": "Project 1",
                "description": "Test project 1",
                "status": "open"
            },
            {
                "name": "Project 2",
                "description": "Test project 2",
                "status": "closed"
            },
            {
                "name": "Project 3",
                "description": "Test project 3",
                "status": "hold"
            }
        ]

        self.test_json = {
            "projects": self.test_projects
        }

        # Configure mock
        self.mock_provider.getJson.return_value = self.test_json

    def test_process_command_valid(self):
        """Test processing a valid command."""
        self.project_manager.commands["mock"] = MagicMock(return_value="Mock command")
        result = self.project_manager.process_command_legacy("mock", [])
        self.assertEqual(result, "Mock command")
        self.project_manager.commands["mock"].assert_called_once_with([])

    def test_process_command_invalid(self):
        """Test processing an invalid command."""
        self.project_manager._get_help = MagicMock(return_value="Help text")
        result = self.project_manager.process_command_legacy("invalid_command", [])
        self.assertEqual(result, "Help text")
        self.project_manager._get_help.assert_called_once()

    def test_get_help(self):
        """Test getting help text."""
        result = self.project_manager._get_help()
        self.assertIn("Projects Command Manual", result)

        # Test help for specific command
        result = self.project_manager._get_help([ProjectCommands.LIST.value])
        self.assertIn("Command: list", result)

        # Test help for invalid command
        result = self.project_manager._get_help(["invalid_command"])
        self.assertEqual(result, "Command invalid_command not found")

    def test_list_projects_default(self):
        """Test listing projects with default status (open)."""
        result = self.project_manager._list_projects([])
        self.assertIn("Projects with status open:", result)
        self.assertIn("01: Project_1", result)
        self.assertNotIn("Project_2", result)  # Project 2 is closed

    def test_list_projects_specific_status(self):
        """Test listing projects with a specific status."""
        result = self.project_manager._list_projects(["closed"])
        self.assertIn("Projects with status closed:", result)
        self.assertIn("01: Project_2", result)
        self.assertNotIn("Project_1", result)  # Project 1 is open

    def test_list_projects_invalid_status(self):
        """Test listing projects with an invalid status."""
        result = self.project_manager._list_projects(["invalid"])
        self.assertEqual(result, "Invalid project status invalid")

    def test_cat_project_exist(self):
        """Test viewing a project that exists."""
        result = self.project_manager._cat_project(["Project_1"])
        self.assertIn("Project 1", result)
        self.assertIn("Test project 1", result)
        self.assertIn("open", result)

    def test_cat_project_not_exist(self):
        """Test viewing a project that doesn't exist."""
        result = self.project_manager._cat_project(["NonExistent"])
        self.assertEqual(result, "Project NonExistent not found")

    def test_cat_project_no_name(self):
        """Test viewing a project without providing a name."""
        result = self.project_manager._cat_project([])
        self.assertEqual(result, "No project name provided")

    def test_edit_project_description_exist(self):
        """Test editing the description of an existing project."""
        result = self.project_manager._edit_project_description(["Project_1", "Updated", "description"])
        self.assertEqual(result, "Description updated for Project_1 successfully")

        # Verify the project's description was updated in the JSON
        self.assertEqual(self.test_projects[0]["description"], "Updated description")
        self.mock_provider.saveJson.assert_called_once_with(self.test_json)

    def test_edit_project_description_not_exist(self):
        """Test editing the description of a non-existent project."""
        result = self.project_manager._edit_project_description(["NonExistent", "Updated", "description"])
        self.assertEqual(result, "Project NonExistent not found")
        self.mock_provider.saveJson.assert_not_called()

    def test_edit_project_description_no_args(self):
        """Test editing project description with insufficient arguments."""
        result = self.project_manager._edit_project_description(["Project_1"])
        self.assertEqual(result, "Format: edit project_name new_content")
        self.mock_provider.saveJson.assert_not_called()

    def test_update_project_status(self):
        """Test updating the status of an existing project."""
        result = self.project_manager._update_project_status("Project 1", "closed")
        self.assertEqual(result, "Project {project_name} status updated to {new_status}".format(
            project_name="Project 1", new_status="closed"))
        self.assertEqual(self.test_projects[0]["status"], "closed")
        self.mock_provider.saveJson.assert_called_once_with(self.test_json)

    def test_update_project_status_not_exist(self):
        """Test updating the status of a non-existent project."""
        result = self.project_manager._update_project_status("NonExistent", "closed")
        self.assertEqual(result, "Project NonExistent not found")
        self.mock_provider.saveJson.assert_not_called()

    def test_open_project_exist(self):
        """Test opening an existing project."""
        # Mock the _update_project_status method
        self.project_manager._update_project_status = MagicMock(return_value="Project status updated")
        result = self.project_manager._open_project(["Project 2"])
        self.assertEqual(result, "Project status updated")
        self.project_manager._update_project_status.assert_called_once_with("Project 2", "open")

    def test_open_project_new(self):
        """Test creating a new project."""
        result = self.project_manager._open_project(["New_Project", "This", "is", "new"])
        self.assertEqual(result, "Created new project: New Project")

        # Verify the new project was added to the JSON
        new_project = {"name": "New Project", "description": "This is new", "status": "open"}
        self.assertIn(new_project, self.test_json["projects"])
        self.mock_provider.saveJson.assert_called_once_with(self.test_json)

    def test_open_project_no_args(self):
        """Test opening a project without providing a name."""
        result = self.project_manager._open_project([])
        self.assertEqual(result, "Format: open project_name (optional_description)")
        self.mock_provider.saveJson.assert_not_called()

    def test_close_project(self):
        """Test closing an existing project."""
        self.project_manager._update_project_status = MagicMock(return_value="Status updated")
        result = self.project_manager._close_project(["Project 1"])
        self.assertEqual(result, "Status updated")
        self.project_manager._update_project_status.assert_called_once_with("Project 1", "closed")

    def test_close_project_no_args(self):
        """Test closing a project without providing a name."""
        result = self.project_manager._close_project([])
        self.assertEqual(result, "Format: close project_name")

    def test_hold_project(self):
        """Test putting an existing project on hold."""
        self.project_manager._update_project_status = MagicMock(return_value="Status updated")
        result = self.project_manager._hold_project(["Project 1"])
        self.assertEqual(result, "Status updated")
        self.project_manager._update_project_status.assert_called_once_with("Project 1", "hold")

    def test_hold_project_no_args(self):
        """Test putting a project on hold without providing a name."""
        result = self.project_manager._hold_project([])
        self.assertEqual(result, "Format: hold project_name")


if __name__ == "__main__":
    unittest.main()
