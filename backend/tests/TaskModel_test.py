import unittest
from src.taskmodels.TaskModel import TaskModel
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskmodels.TaskIdentity import InvalidTaskIdentityError


class TestTaskModel(unittest.TestCase):
    def test_task_identity_is_optional_and_opaque(self):
        task = TaskModel(
            description="Test task",
            context="work",
            start=0,
            due=0,
            severity=1.0,
            totalCost=1.0,
            investedEffort=0.0,
            status="open",
            calm="false",
            project="",
            index=4,
            raised=None,
            waited=None,
            task_id="  user supplied ID  ",
            identity_path="configured/tasks.json",
        )

        self.assertEqual(task.getTaskUID(), "  user supplied ID  ")
        self.assertEqual(task._identity_path, "configured/tasks.json")

    def test_task_model_derives_an_identity_from_its_configured_location(self):
        task = TaskModel(
            description="Test task",
            context="work",
            start=0,
            due=0,
            severity=1.0,
            totalCost=1.0,
            investedEffort=0.0,
            status="open",
            calm="false",
            project="",
            index=4,
            raised=None,
            waited=None,
            identity_path="configured/tasks.json",
        )

        self.assertEqual(task.getTaskUID(), fallback_task_id("Test task", "configured/tasks.json", 4))

    def test_model_equality_uses_task_identity_instead_of_array_position(self):
        common = {
            "description": "Test task",
            "context": "work",
            "start": 0,
            "due": 0,
            "severity": 1.0,
            "totalCost": 1.0,
            "investedEffort": 0.0,
            "status": "open",
            "calm": "false",
            "project": "",
            "raised": None,
            "waited": None,
        }
        first = TaskModel(**common, index=0, task_id="first")
        same_identity_at_new_position = TaskModel(**common, index=4, task_id="first")
        other_identity_at_same_position = TaskModel(**common, index=0, task_id="second")

        self.assertEqual(first, same_identity_at_new_position)
        self.assertNotEqual(first, other_identity_at_same_position)

    def test_explicit_task_id_must_be_non_empty_opaque_string(self):
        common = {
            "description": "Test task",
            "context": "work",
            "start": 0,
            "due": 0,
            "severity": 1.0,
            "totalCost": 1.0,
            "investedEffort": 0.0,
            "status": "open",
            "calm": "false",
            "project": "",
            "index": 0,
            "raised": None,
            "waited": None,
        }
        for invalid_id in ("", " \t\n ", 42, ["id"]):
            with self.subTest(task_id=invalid_id):
                with self.assertRaises(InvalidTaskIdentityError):
                    TaskModel(**common, task_id=invalid_id)

        opaque_id = "  x/y : 00  "
        task = TaskModel(**common, task_id=opaque_id)
        self.assertEqual(task.getTaskUID(), opaque_id)

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
            index=1,
            raised=None,
            waited=None
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
            index=1,
            raised=None,
            waited=None
        )

        # Description should include the project name appended with " @ "
        self.assertEqual(task.getDescription(), "Test task @ TestProject")


if __name__ == "__main__":
    unittest.main()
