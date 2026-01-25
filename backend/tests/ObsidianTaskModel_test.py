import unittest
from src.taskmodels.ObsidianTaskModel import ObsidianTaskModel


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
        expected_description = "(Test Context) Test Task @ 'test_file:10'"
        self.assertEqual(self.task.getDescription(), expected_description)

    def test_getDescription_withLinuxSubdirectory(self):
        self.task.setFile("subdirectory/test_file.md")
        expected_description = "(Test Context) Test Task @ 'test_file:10'"
        self.assertEqual(self.task.getDescription(), expected_description)

    def test_getDescription_withWindowsSubdirectory(self):
        self.task.setFile("subdirectory\\test_file.md")
        expected_description = "(Test Context) Test Task @ 'test_file:10'"
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
