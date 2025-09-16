import unittest
from unittest.mock import MagicMock

from src.ProjectManager import ObsidianProjectManager
from src.Interfaces.IProjectManager import ProjectCommands
from src.Interfaces.IFileBroker import VaultRegistry


class TestObsidianProjectManager(unittest.TestCase):
    def setUp(self):
        # Create mock objects for dependencies
        self.mock_task_provider = MagicMock()
        self.mock_file_broker = MagicMock()

        # Create instance of ObsidianProjectManager with mocked dependencies
        self.project_manager = ObsidianProjectManager(
            self.mock_task_provider,
            self.mock_file_broker
        )

    def test_get_help(self):
        # Test _get_help method
        help_message = self.project_manager._get_help()
        self.assertIn("# Projects Command Manual", help_message)
        for cmd in ProjectCommands.values():
            self.assertIn(cmd, help_message)

    def test_process_command_with_valid_command(self):
        # Mock _list_projects to verify it's called
        callableMock = MagicMock(return_value="Mocked list result")
        self.project_manager.commands[ProjectCommands.LIST.value] = callableMock

        # Test process_command with a valid command
        result = self.project_manager.process_command(ProjectCommands.LIST.value, ["open"])

        # Verify the _list_projects method was called with the correct arguments
        callableMock.assert_called_once_with(["open"])
        self.assertEqual(result, "Mocked list result")

    def test_process_command_with_invalid_command(self):
        # Test process_command with an invalid command
        result = self.project_manager.process_command("invalid_command", [])

        # Should return help message
        self.assertIn("# Projects Command Manual", result)

    def test_list_projects_valid_status(self):
        # Setup mock data
        mock_projects = [
            {"name": "Project 1", "status": "open", "path": "project1.md"},
            {"name": "Project 2", "status": "closed", "path": "project2.md"},
            {"name": "Project 3", "status": "open", "path": "project3.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects

        # Test list_projects with valid status
        result = self.project_manager._list_projects(["open"])

        # Verify results
        self.assertIn("Projects with status open:", result)
        self.assertIn("Project_1", result)
        self.assertIn("Project_3", result)
        self.assertNotIn("Project_2", result)

    def test_list_projects_invalid_status(self):
        # Test list_projects with invalid status
        result = self.project_manager._list_projects(["invalid_status"])

        # Should return error message
        self.assertEqual("Invalid project status invalid_status", result)

    def test_cat_project_success(self):
        # Setup mock data
        mock_projects = [
            {"name": "Project 1", "status": "open", "path": "project1.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects
        self.mock_file_broker.getVaultFileLines.return_value = ["Line 1\n", "Line 2\n"]

        # Test cat_project with valid project
        result = self.project_manager._cat_project(["Project_1"])

        # Verify results
        self.mock_file_broker.getVaultFileLines.assert_called_once_with(VaultRegistry.OBSIDIAN, "project1.md")
        self.assertIn("001: Line 1", result)
        self.assertIn("002: Line 2", result)

    def test_cat_project_not_found(self):
        # Setup mock data (empty list = no projects found)
        self.mock_task_provider.getTaskListAttribute.return_value = []

        # Test cat_project with non-existent project
        result = self.project_manager._cat_project(["Nonexistent_Project"])

        # Verify results
        self.assertEqual("Project Nonexistent_Project not found", result)

    def test_edit_project_line_success(self):
        # Setup mock data
        mock_projects = [
            {"name": "Project 1", "status": "open", "path": "project1.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects
        self.mock_file_broker.getVaultFileLines.return_value = ["Line 1\n", "Line 2\n", "Line 3\n"]

        # Test edit_project_line with valid inputs
        result = self.project_manager._edit_project_line(["Project_1", "2", "Updated line 2"])

        # Verify the line was updated correctly
        expected_lines = ["Line 1\n", "Updated line 2\n", "Line 3\n"]
        self.mock_file_broker.writeVaultFileLines.assert_called_once_with(
            VaultRegistry.OBSIDIAN, "project1.md", expected_lines
        )
        self.assertIn("updated successfully", result)

    def test_add_project_line_success(self):
        # Setup mock data
        mock_projects = [
            {"name": "Project 1", "status": "open", "path": "project1.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects
        self.mock_file_broker.getVaultFileLines.return_value = ["Line 1\n", "Line 3\n"]

        # Test add_project_line with valid inputs
        result = self.project_manager._add_project_line(["Project_1", "2", "New line 2"])

        # Verify the line was added correctly
        expected_lines = ["Line 1\n", "New line 2\n", "Line 3\n"]
        self.mock_file_broker.writeVaultFileLines.assert_called_once_with(
            VaultRegistry.OBSIDIAN, "project1.md", expected_lines
        )
        self.assertIn("Line added at position 2", result)

    def test_remove_project_line_success(self):
        # Setup mock data
        mock_projects = [
            {"name": "Project 1", "status": "open", "path": "project1.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects
        self.mock_file_broker.getVaultFileLines.return_value = ["Line 1\n", "Line 2\n", "Line 3\n"]

        # Test remove_project_line with valid inputs
        result = self.project_manager._remove_project_line(["Project_1", "2"])

        # Verify the line was removed correctly
        expected_lines = ["Line 1\n", "Line 3\n"]
        self.mock_file_broker.writeVaultFileLines.assert_called_once_with(
            VaultRegistry.OBSIDIAN, "project1.md", expected_lines
        )
        self.assertIn("Line 2 removed", result)

    def test_update_project_status_existing_status(self):
        # Setup mock data - project with existing status field in frontmatter
        mock_projects = [
            {"name": "Project 1", "status": "open", "path": "project1.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "title: Project 1\n",
            "project: open\n",
            "---\n",
            "# Project 1\n"
        ]

        # Test updating project status
        result = self.project_manager._update_project_status("Project 1", "hold")

        # Verify the status was updated correctly
        expected_lines = [
            "---\n",
            "title: Project 1\n",
            "project: hold\n",
            "---\n",
            "# Project 1\n"
        ]
        self.mock_file_broker.writeVaultFileLines.assert_called_once_with(
            VaultRegistry.OBSIDIAN, "project1.md", expected_lines
        )
        self.assertEqual("Project Project 1 is now hold", result)

    def test_open_project_new_project(self):
        # Setup mock data (empty list = no projects found)
        self.mock_task_provider.getTaskListAttribute.return_value = []

        # Test opening a new project
        result = self.project_manager._open_project(["New_Project"])

        # Verify a new project file was created
        self.mock_file_broker.writeVaultFileLines.assert_called_once()
        call_args = self.mock_file_broker.writeVaultFileLines.call_args[0]
        self.assertEqual(call_args[0], VaultRegistry.OBSIDIAN)
        self.assertEqual(call_args[1], "New Project.md")
        # Check that content contains frontmatter with project status
        self.assertTrue(any("project: open" in line for line in call_args[2]))
        self.assertEqual("Created new project: New Project", result)

    def test_open_project_existing(self):
        # Setup mock for _update_project_status
        self.project_manager._update_project_status = MagicMock(return_value="Project Test Project is now open")

        # Setup mock data for existing project
        mock_projects = [
            {"name": "Test Project", "status": "closed", "path": "test_project.md"}
        ]
        self.mock_task_provider.getTaskListAttribute.return_value = mock_projects

        # Test opening an existing project
        result = self.project_manager._open_project(["Test_Project"])

        # Verify _update_project_status was called
        self.project_manager._update_project_status.assert_called_once_with("Test_Project", "open")
        self.assertEqual("Project Test Project is now open", result)

    def test_close_project(self):
        # Setup mock for _update_project_status
        self.project_manager._update_project_status = MagicMock(return_value="Project Test Project is now closed")

        # Test closing a project
        result = self.project_manager._close_project(["Test_Project"])

        # Verify _update_project_status was called
        self.project_manager._update_project_status.assert_called_once_with("Test_Project", "closed")
        self.assertEqual("Project Test Project is now closed", result)

    def test_hold_project(self):
        # Setup mock for _update_project_status
        self.project_manager._update_project_status = MagicMock(return_value="Project Test Project is now hold")

        # Test putting a project on hold
        result = self.project_manager._hold_project(["Test_Project"])

        # Verify _update_project_status was called
        self.project_manager._update_project_status.assert_called_once_with("Test_Project", "hold")
        self.assertEqual("Project Test Project is now hold", result)


if __name__ == "__main__":
    unittest.main()
