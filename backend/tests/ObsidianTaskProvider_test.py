import hashlib
import json
import unittest
from unittest.mock import MagicMock
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, MissingTaskIdentityError
from src.wrappers.TimeManagement import TimePoint
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.Interfaces.ITaskJsonProvider import ITaskJsonProvider
from src.Interfaces.IFileBroker import IFileBroker
from src.taskmodels.ObsidianTaskModel import ObsidianTaskModel


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

    def test_getTaskList_reads_fresh_parse_without_running_discovery(self):
        task_json = self.GetCurrentTaskJson()
        open_task = dict(task_json["tasks"][0])
        open_task["taskText"] = "Open task"
        open_task["status"] = " "
        task_json["tasks"].append(open_task)
        self.mockTaskJsonProvider.getJson.return_value = task_json

        active = self.provider.getTaskList()
        all_tasks = self.provider.getTaskList(include_completed=True)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].getStatus(), " ")
        self.assertEqual(len(all_tasks), 2)
        self.assertEqual({task.getStatus() for task in all_tasks}, {" ", "x"})
        self.assertEqual(self.mockTaskJsonProvider.getJson.call_count, 2)
        self.mockTaskJsonProvider.discover.assert_not_called()

    def test_getTaskList_propagates_read_errors(self):
        self.mockTaskJsonProvider.getJson.side_effect = PermissionError("vault is unreadable")

        with self.assertRaisesRegex(PermissionError, "vault is unreadable"):
            self.provider.getTaskList()

    def test_discard_pending_task_reservations_is_noop(self):
        self.assertIsNone(self.provider.discardPendingTaskReservations())

    def test_saveTask_persists_fallback_and_preserves_unknown_vault_content(self):
        original_lines = [
            "---\n",
            "owner: planning\n",
            "---\n",
            "- [X] Original title [track:: work] [custom:: retain] [due:: 2026-10-06]\n",
            "%% Keep this note %%\n",
            "- [x] Completed task [track:: work]\n",
        ]
        self.mockFileBroker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mockFileBroker.getVaultFileLines.return_value = list(original_lines)
        task_id = fallback_task_id("Original title", "tasks.md", 3)
        task = ObsidianTaskModel(
            description="Original title",
            context="work",
            start=TimePoint.today().as_int(),
            due=TimePoint.today().as_int(),
            severity=2,
            totalCost=1,
            investedEffort=0,
            status="x",
            file="tasks.md",
            line=3,
            calm="true",
            raised=None,
            waited=None,
        )
        task.setDescription("Edited title")

        self.provider.saveTask(task)

        self.mockFileBroker.writeVaultFileLines.assert_called_once()
        args = self.mockFileBroker.writeVaultFileLines.call_args.args
        saved_lines = args[2]
        self.assertEqual(saved_lines[:3], original_lines[:3])
        self.assertIn("[custom:: retain]", saved_lines[3])
        self.assertIn(f"[id:: {task_id}]", saved_lines[3])
        self.assertTrue(saved_lines[3].startswith("- [X] Edited title"))
        self.assertEqual(saved_lines[4:], original_lines[4:])
        self.assertEqual(task.getTaskUID(), task_id)

    def test_saveTask_new_task_appends_with_prepared_id_and_keeps_completed_content(self):
        original = "# Personal tasks\n\n- [x] Keep completed [track:: work]\n"
        self.mockFileBroker.readFileContent.return_value = original
        self.mockFileBroker.getVaultFiles.return_value = []
        task = self.provider.createDefaultTask("New task")
        expected_id = fallback_task_id("New task", "ObsidianTaskProvider.md", 3)

        self.provider.saveTask(task)

        saved_content = self.mockFileBroker.writeFileContent.call_args.args[1]
        self.assertTrue(saved_content.startswith(original))
        self.assertIn(f"[id:: {expected_id}]", saved_content)
        self.assertEqual(task.getTaskUID(), expected_id)
        self.assertEqual(task.getLine(), 3)

    def test_new_task_reservations_get_distinct_ids_before_writing(self):
        self.mockFileBroker.readFileContent.return_value = "# Personal tasks\n\n"
        self.mockFileBroker.getVaultFiles.return_value = []
        first = self.provider.createDefaultTask("First task")
        second = self.provider.createDefaultTask("Second task")

        self.assertNotEqual(first.getTaskUID(), second.getTaskUID())
        self.assertNotEqual(first.getLine(), second.getLine())

    def test_saveTask_rejects_missing_identity_without_writing(self):
        self.mockFileBroker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mockFileBroker.getVaultFileLines.return_value = ["- [ ] Existing [track:: work] [id:: existing]\n"]
        task = self._task_with_id("missing", file="tasks.md", line=0)

        with self.assertRaises(MissingTaskIdentityError):
            self.provider.saveTask(task)

        self.mockFileBroker.writeVaultFileLines.assert_not_called()

    def test_saveTask_rejects_duplicate_identity_before_writing(self):
        self.mockFileBroker.getVaultFiles.return_value = [("a.md", 100.0), ("b.md", 100.0)]
        self.mockFileBroker.getVaultFileLines.side_effect = lambda _, path: [
            f"- [ ] {path} [track:: work] [id:: duplicated]\n"
        ]
        task = self._task_with_id("duplicated", file="a.md", line=0)

        with self.assertRaises(AmbiguousTaskIdentityError):
            self.provider.saveTask(task)

        self.mockFileBroker.writeVaultFileLines.assert_not_called()

    def _task_with_id(self, task_id: str, *, file: str, line: int) -> ObsidianTaskModel:
        return ObsidianTaskModel(
            description="Existing",
            context="work",
            start=TimePoint.today().as_int(),
            due=TimePoint.today().as_int(),
            severity=1,
            totalCost=1,
            investedEffort=0,
            status=" ",
            file=file,
            line=line,
            calm="false",
            raised=None,
            waited=None,
            task_id=task_id,
        )

    def GetCurrentTaskJson(self) -> dict:
        return {
            "tasks": [
                {
                    "taskText": "Task 1",
                    "track": "track 1",
                    "starts": "1741906800000",
                    "due": TimePoint.today().as_int(),
                    "severity": "1",
                    "total_cost": "1",
                    "effort_invested": "1",
                    "status": "x",
                    "file": "file 1",
                    "line": "1",
                    "calm": "true"
                }
            ],
        }

    def fromObsidianToGenericJsonDumps(self, obsidianJson: dict) -> str:
        retval = {
            "tasks": [],
        }

        for task in obsidianJson["tasks"]:
            slash = "/"
            dot = "."
            text = task["taskText"]
            _file = task["file"]
            _line = task["line"]

            hash_input = f"{text}{_file}{_line}"
            task_uid = hashlib.md5(hash_input.encode()).hexdigest()[0:5]

            retval["tasks"].append({
                "id": hashlib.md5(hash_input.encode()).hexdigest(),
                "description": f"({task['track']}) {text} @ '{_file.split(slash).pop().split(dot)[0]}:{_line}' [{task_uid}]",
                "context": task["track"],
                "start": str(int(task["starts"])),
                "due": str(int(task["due"])),
                "severity": str(float(task["severity"])),
                "totalCost": str(float(task["total_cost"])),
                "investedEffort": str(float(task["effort_invested"])),
                "status": task["status"],
                "calm": str(bool(task["calm"]))
            })

        return bytearray(json.dumps(retval, indent=4), "utf-8").decode("utf-8")


if __name__ == '__main__':
    unittest.main()
