import unittest
from src.ObsidianTaskModel import ObsidianTaskModel

class TestObsidianTaskModel(unittest.TestCase):

    def setUp(self):
        self.task = ObsidianTaskModel(
            description="Test Task",
            context="Test Context",
            start=1633024800000,
            due=1633111200000,
            severity=1.0,
            totalCost=10.0,
            investedEffort=5.0,
            status="Open",
            file="test_file.md",
            line=10,
            calm="True"
        )

    def test_getDescription(self):
        self.assertEqual(self.task.getDescription(), "Test Task @ 'test_file:10'")

    def test_getContext(self):
        self.assertEqual(self.task.getContext(), "Test Context")

    def test_getStart(self):
        self.assertEqual(self.task.getStart(), 1633024800000)

    def test_getDue(self):
        self.assertEqual(self.task.getDue(), 1633111200000)

    def test_getSeverity(self):
        self.assertEqual(self.task.getSeverity(), 1.0)

    def test_getTotalCost(self):
        self.assertEqual(self.task.getTotalCost(), 10.0)

    def test_getInvestedEffort(self):
        self.assertEqual(self.task.getInvestedEffort(), 5.0)

    def test_getStatus(self):
        self.assertEqual(self.task.getStatus(), "Open")

    def test_getFile(self):
        self.assertEqual(self.task.getFile(), "test_file.md")

    def test_getLine(self):
        self.assertEqual(self.task.getLine(), 10)

    def test_getCalm(self):
        self.assertTrue(self.task.getCalm())

    def test_setDescription(self):
        self.task.setDescription("New Description")
        self.assertEqual(self.task.getDescription(), "New Description @ 'test_file:10'")

    def test_setContext(self):
        self.task.setContext("New Context")
        self.assertEqual(self.task.getContext(), "New Context")

    def test_setStart(self):
        self.task.setStart(1633204800000)
        self.assertEqual(self.task.getStart(), 1633204800000)

    def test_setDue(self):
        self.task.setDue(1633291200000)
        self.assertEqual(self.task.getDue(), 1633291200000)

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
        self.assertEqual(self.task.calculateRemainingTime(), 1.5)

    def test_equality(self):
        task2 = ObsidianTaskModel(
            description="Test Task",
            context="Test Context",
            start=1633024800000,
            due=1633111200000,
            severity=1.0,
            totalCost=10.0,
            investedEffort=5.0,
            status="Open",
            file="test_file.md",
            line=10,
            calm="True"
        )
        self.assertEqual(self.task, task2)

if __name__ == '__main__':
    unittest.main()
