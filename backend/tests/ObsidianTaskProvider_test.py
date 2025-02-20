import json
import unittest
from unittest.mock import MagicMock
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker


class TestObsidianTaskProvider(unittest.TestCase):

    def setUp(self):
        self.mockTaskJsonProvider = MagicMock(spec=ITaskJsonProvider)
        self.mockFileBroker = MagicMock(spec=IFileBroker)
        self.provider = ObsidianTaskProvider(self.mockTaskJsonProvider, self.mockFileBroker, True)

    def tearDown(self):
        self.provider.dispose()

    def test_exportTasks(self):
        # Arrange
        currentTaskJson: dict = self.GetCurrentTaskJson()
        self.mockTaskJsonProvider.getJson.return_value = currentTaskJson

        # Act
        testClass = self.provider
        retval = testClass.exportTasks("json").decode("utf-8")

        # Assert
        self.assertEqual(testClass.lastJson, currentTaskJson)
        self.assertEqual(retval, self.fromObsidianToGenericJsonDumps(currentTaskJson))
        pass

    def GetCurrentTaskJson(self) -> dict:
        return {
            "tasks": [
                {
                    "taskText": "Task 1",
                    "track": "track 1",
                    "starts": "1741906800000",
                    "due": "1741906800000",
                    "severity": "1",
                    "total_cost": "1",
                    "effort_invested": "1",
                    "status": "x",
                    "file": "file 1",
                    "line": "1",
                    "calm": "true"
                }
            ],
            "pomodoros_per_day": "2",
        }

    def fromObsidianToGenericJsonDumps(self, obsidianJson: dict) -> str:
        retval = {
            "tasks": [],
            "pomodoros_per_day": "2",
        }

        for task in obsidianJson["tasks"]:
            slash = "/"
            dot = "."
            text = task["taskText"]
            _file = task["file"]
            _line = task["line"]
        
            retval["tasks"].append({
                "description": f"{text} @ '{_file.split(slash).pop().split(dot)[0]}:{_line}'",
                "context": task["track"],
                "start": int(task["starts"]),
                "due": int(task["due"]),
                "severity": float(task["severity"]),
                "totalCost": float(task["total_cost"]),
                "investedEffort": float(task["effort_invested"]),
                "status": task["status"],
                "calm": bool(task["calm"])
            })

        return bytearray(json.dumps(retval, indent=4), "utf-8").decode("utf-8")


if __name__ == '__main__':
    unittest.main()
