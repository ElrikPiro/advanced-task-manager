import hashlib
import unittest
from src.taskmodels.ObsidianTaskModel import ObsidianTaskModel
from src.taskmodels.TaskIdentity import InvalidTaskIdentityError


class TestObsidianTaskModel(unittest.TestCase):

    def setUp(self):
        # Use valid timestamps instead of 1 and 2
        import time
        current_time = int(time.time() * 1000)  # Current time in milliseconds
        future_time = current_time + (24 * 60 * 60 * 1000)  # 24 hours later
        
        self.task = ObsidianTaskModel(
            description="Test Task",
            context="Test Context",
            start=current_time,
            due=future_time,
            severity=3.0,
            totalCost=4.0,
            investedEffort=5.0,
            status="Pending",
            file="test_file.md",
            line=10,
            calm="True",
            raised=None,
            waited=None
        )

    def test_getDescription(self):
        expected_uid = self.task.getTaskUID()[0:5]
        expected_description = f"(Test Context) Test Task @ 'test_file:10' [{expected_uid}]"
        self.assertEqual(self.task.getDescription(), expected_description)

    def test_getDescription_withLinuxSubdirectory(self):
        self.task.setFile("subdirectory/test_file.md")
        expected_uid = self.task.getTaskUID()[0:5]
        expected_description = f"(Test Context) Test Task @ 'test_file:10' [{expected_uid}]"
        self.assertEqual(self.task.getDescription(), expected_description)

    def test_getDescription_withWindowsSubdirectory(self):
        self.task.setFile("subdirectory\\test_file.md")
        expected_uid = self.task.getTaskUID()[0:5]
        expected_description = f"(Test Context) Test Task @ 'test_file:10' [{expected_uid}]"
        self.assertEqual(self.task.getDescription(), expected_description)

    def test_getFile(self):
        self.assertEqual(self.task.getFile(), "test_file.md")

    def test_getLine(self):
        self.assertEqual(self.task.getLine(), 10)

    def test_setFile(self):
        self.task.setFile("new_file.md")
        self.assertEqual(self.task.getFile(), "new_file.md")

    def test_setLine(self):
        self.task.setLine(20)
        self.assertEqual(self.task.getLine(), 20)

    def test_getTaskUID_uses_the_existing_fallback_formula(self):
        expected = hashlib.md5(b"Test Tasktest_file.md10").hexdigest()
        self.assertEqual(self.task.getTaskUID(), expected)

    def test_getTaskUID_is_frozen_when_task_is_edited_or_moved(self):
        task_id = self.task.getTaskUID()
        self.task.setDescription("Updated task")
        self.task.setFile("archive/test_file.md")
        self.task.setLine(20)
        self.assertEqual(self.task.getTaskUID(), task_id)

    def test_explicit_task_uid_is_opaque_and_stable(self):
        task = ObsidianTaskModel(
            description="Task",
            context="work",
            start=self.task.getStart().as_int(),
            due=self.task.getDue().as_int(),
            severity=1,
            totalCost=1,
            investedEffort=0,
            status=" ",
            file="tasks.md",
            line=0,
            calm="false",
            raised=None,
            waited=None,
            task_id=" opaque/id ",
        )
        task.setDescription("Changed")
        task.setFile("moved.md")
        self.assertEqual(task.getTaskUID(), " opaque/id ")

    def test_explicit_whitespace_only_task_uid_is_rejected(self):
        with self.assertRaises(InvalidTaskIdentityError):
            ObsidianTaskModel(
                description="Task",
                context="work",
                start=self.task.getStart().as_int(),
                due=self.task.getDue().as_int(),
                severity=1,
                totalCost=1,
                investedEffort=0,
                status=" ",
                file="tasks.md",
                line=0,
                calm="false",
                raised=None,
                waited=None,
                task_id="   ",
            )

    def test_eq(self):
        # Use valid timestamps (current time for start, future time for due)
        import time
        current_time = int(time.time() * 1000)  # Current time in milliseconds
        future_time = current_time + (24 * 60 * 60 * 1000)  # 24 hours later
        
        other_task = ObsidianTaskModel(
            description="Test Task",
            context="Test Context",
            start=current_time,
            due=future_time,
            severity=3.0,
            totalCost=4.0,
            investedEffort=5.0,
            status="Pending",
            file="test_file.md",
            line=10,
            calm="True",
            raised=None,
            waited=None
        )
        
        # Update self.task to use the same timestamps for comparison
        self.task._start = current_time
        self.task._due = future_time
        
        self.assertTrue(self.task == other_task)

    def test_not_eq(self):
        other_task = ObsidianTaskModel(
            description="Different Task",
            context="Different Context",
            start=1,
            due=2,
            severity=3.0,
            totalCost=4.0,
            investedEffort=5.0,
            status="Pending",
            file="test_file.md",
            line=10,
            calm="True",
            raised=None,
            waited=None
        )
        self.assertFalse(self.task == other_task)

    def test_getProject(self):
        self.assertEqual(self.task.getProject(), "test_file:10")

    def test_getProject_withSubdirectory(self):
        self.task.setFile("subdirectory/test_file.md")
        self.assertEqual(self.task.getProject(), "test_file:10")

    def test_getProject_withWindowsPath(self):
        self.task.setFile("C:\\Users\\test\\Documents\\test_file.md")
        self.assertEqual(self.task.getProject(), "test_file:10")

    def test_getProject_withMultipleExtensions(self):
        self.task.setFile("test_file.backup.md")
        self.assertEqual(self.task.getProject(), "test_file:10")

    def test_getProject_afterChangingLine(self):
        self.task.setLine(25)
        self.assertEqual(self.task.getProject(), "test_file:25")


if __name__ == '__main__':
    unittest.main()
