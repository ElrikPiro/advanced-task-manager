import unittest
from datetime import datetime, timedelta
from src.TaskModel import TaskModel

class TaskModelTests(unittest.TestCase):
    def setUp(self):
        self.task = TaskModel(
            description="Test Task",
            context="Test Context",
            start=int((datetime.now() - timedelta(days=1)).timestamp() * 1000),
            due=int((datetime.now() + timedelta(days=1)).timestamp() * 1000),
            severity=1.0,
            totalCost=10.0,
            investedEffort=5.0,
            status="Open",
            calm="True",
            index=1
        )

    def test_getDescription(self):
        self.assertEqual(self.task.getDescription(), "Test Task")

    def test_getContext(self):
        self.assertEqual(self.task.getContext(), "Test Context")

    def test_getStart(self):
        self.assertEqual(self.task.getStart(), int((datetime.now() - timedelta(days=1)).timestamp() * 1000))

    def test_getDue(self):
        self.assertEqual(self.task.getDue(), int((datetime.now() + timedelta(days=1)).timestamp() * 1000))

    def test_getSeverity(self):
        self.assertEqual(self.task.getSeverity(), 1.0)

    def test_getTotalCost(self):
        self.assertEqual(self.task.getTotalCost(), 10.0)

    def test_getInvestedEffort(self):
        self.assertEqual(self.task.getInvestedEffort(), 5.0)

    def test_getStatus(self):
        self.assertEqual(self.task.getStatus(), "Open")

    def test_getCalm(self):
        self.assertTrue(self.task.getCalm())

    def test_setDescription(self):
        self.task.setDescription("New Description")
        self.assertEqual(self.task.getDescription(), "New Description")

    def test_setContext(self):
        self.task.setContext("New Context")
        self.assertEqual(self.task.getContext(), "New Context")

    def test_setStart(self):
        new_start = int((datetime.now() - timedelta(days=2)).timestamp() * 1000)
        self.task.setStart(new_start)
        self.assertEqual(self.task.getStart(), new_start)

    def test_setDue(self):
        new_due = int((datetime.now() + timedelta(days=2)).timestamp() * 1000)
        self.task.setDue(new_due)
        self.assertEqual(self.task.getDue(), new_due)

    def test_setSeverity(self):
        self.task.setSeverity(2.0)
        self.assertEqual(self.task.getSeverity(), 2.0)

    def test_setTotalCost(self):
        self.task.setTotalCost(20.0)
        self.assertEqual(self.task.getTotalCost(), 20.0)

    def test_setInvestedEffort(self):
        self.task.setInvestedEffort(10.0)
        self.assertEqual(self.task.getInvestedEffort(), 10.0)

    def test_setStatus(self):
        self.task.setStatus("Closed")
        self.assertEqual(self.task.getStatus(), "Closed")

    def test_setCalm(self):
        self.task.setCalm(False)
        self.assertFalse(self.task.getCalm())

    def test_calculateRemainingTime(self):
        self.assertEqual(self.task.calculateRemainingTime(), 2.5)

    def test_equality(self):
        task2 = TaskModel(
            description="Test Task",
            context="Test Context",
            start=int((datetime.now() - timedelta(days=1)).timestamp() * 1000),
            due=int((datetime.now() + timedelta(days=1)).timestamp() * 1000),
            severity=1.0,
            totalCost=10.0,
            investedEffort=5.0,
            status="Open",
            calm="True",
            index=1
        )
        self.assertEqual(self.task, task2)

if __name__ == '__main__':
    unittest.main()
