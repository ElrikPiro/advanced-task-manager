import unittest
from src.taskmodels.TaskModel import TaskModel


class TestTaskModel(unittest.TestCase):
    def test_getDescription_no_project(self):
        """Test getDescription when no project is assigned"""
        # Create a task with empty project
        task = TaskModel(
            description="Test task",
            context="Test context",
            start=0,
            due=0,
            severity=1.0,
            totalCost=1.0,
            investedEffort=0.0,
            status="open",
            calm="true",
            project="",
            index=1
        )

        # Description should match the task description without any project suffix
        self.assertEqual(task.getDescription(), "Test task")

    def test_getDescription_with_project(self):
        """Test getDescription when a project is assigned"""
        # Create a task with a project
        task = TaskModel(
            description="Test task",
            context="Test context",
            start=0,
            due=0,
            severity=1.0,
            totalCost=1.0,
            investedEffort=0.0,
            status="open",
            calm="true",
            project="TestProject",
            index=1
        )

        # Description should include the project name appended with " @ "
        self.assertEqual(task.getDescription(), "Test task @ TestProject")


if __name__ == "__main__":
    unittest.main()
