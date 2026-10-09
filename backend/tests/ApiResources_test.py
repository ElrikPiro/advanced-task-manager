import datetime
import os
import unittest
from typing import Any, cast

from src.MutationCoordinator import OperationFailure, OperationReceipt
from src.Utils import (
    ExtendedTaskInformation,
    TaskEntry,
    TaskHeuristicsInfo,
    TaskInformation,
    TaskListContent,
)
from src.api.ApiResources import ApiResources
from src.domain.errors import DomainCalculationError
from src.domain.models import OperationIntent, OperationResult, OperationTarget, TaskView
from src.taskmodels.TaskModel import TaskModel
from src.wrappers.TimeManagement import TimePoint


class FakeApplication:
    def __init__(self, task: TaskModel) -> None:
        self.task = task
        self.query_content = TaskListContent(
            algorithm_name="EDF",
            algorithm_desc="Earliest due date",
            sort_heuristic="Slack",
            tasks=[TaskEntry(
                id=task.getTaskUID(),
                description=task.getDescription(),
                context=task.getContext(),
                start=str(task.getStart()),
                due=str(task.getDue()),
                severity=task.getSeverity(),
                status=task.getStatus(),
                total_cost=task.getTotalCost().as_pomodoros(),
                effort_invested=task.getInvestedEffort().as_pomodoros(),
                heuristic_value=2.5,
            )],
            total_tasks=1,
            current_page=2,
            total_pages=3,
            active_filters=[],
            interactive=True,
        )
        self.heuristic_value = 2.5
        self.operation_executions = 0

    def query_tasks(self, view: TaskView) -> TaskListContent:
        return self.query_content

    def read_task_models(self, *, include_completed: bool = True) -> list[TaskModel]:
        return [self.task]

    def read_task(self, task_id: str) -> TaskModel:
        if task_id != self.task.getTaskUID():
            raise LookupError(task_id)
        return self.task

    def read_task_information_for(
        self,
        task: TaskModel,
        *,
        extended: bool = False,
    ) -> TaskInformation:
        value = self.heuristic_value
        extended_data = ExtendedTaskInformation(
            [TaskHeuristicsInfo("Slack", value, "Days available")],
            "Safe task metadata",
        )
        return TaskInformation(
            self.query_content.tasks[0],
            extended_data if extended else None,
        )

    def project_operation_capabilities(self) -> dict[str, dict[str, Any]]:
        return {
            "open-project": {"target.id": {"type": "string", "required": True}},
            "close-project": {},
            "edit-project-content": {"description": {"type": "string", "required": True}},
        }


def make_task(task_id: str = "task-1", status: str = " ") -> TaskModel:
    start = int(datetime.datetime(2026, 10, 4, 15, 30).timestamp() * 1000)
    due = int(datetime.datetime(2026, 10, 8, 12, 0).timestamp() * 1000)
    return TaskModel(
        "Write report",
        " work ",
        start,
        due,
        3.5,
        2.0,
        1.0,
        status,
        "False",
        "Current Project",
        0,
        " release ",
        " review ",
        task_id=task_id,
    )


class ApiResourcesTest(unittest.TestCase):
    def test_create_and_edit_publish_configured_context_command_prefixes(self) -> None:
        from unittest.mock import Mock
        application = FakeApplication(make_task())
        application.task_context_prefixes = Mock(return_value=("indoor", "outdoor", "alert"))
        resources = ApiResources(cast(Any, application), "/api/v1")
        collection = resources.read_tasks(TaskView())
        create = next(action for action in collection["actions"] if action["name"] == "create-task")
        edit = next(action for action in resources.task_resource(application.task)["actions"] if action["name"] == "edit-task")
        self.assertEqual(create["inputs"]["context"]["startsWithAny"], ["indoor", "outdoor", "alert"])
        self.assertEqual(edit["inputs"]["changes"]["properties"]["context"]["startsWithAny"], ["indoor", "outdoor", "alert"])

    def test_root_and_task_links_keep_the_configured_prefix_and_encode_ids(self) -> None:
        task = make_task("opaque/id & one")
        application = FakeApplication(task)
        resources = ApiResources(cast(Any, application), "/deploy/api/v1/")

        root = resources.read_root()
        collection = resources.read_tasks(
            TaskView(
                filters=("Work", "Home"),
                page=2,
                page_size=1,
                algorithm="EDF",
                heuristic="Slack",
                search=("two words",),
            )
        )

        self.assertEqual(root["_links"]["tasks"]["href"], "/deploy/api/v1/tasks")
        self.assertEqual(root["_links"]["operations"]["href"], "/deploy/api/v1/operations")
        self.assertEqual(root["_links"]["operations"]["method"], "POST")
        embedded = collection["_embedded"]["tasks"][0]
        self.assertEqual(
            embedded["_links"]["self"]["href"],
            "/deploy/api/v1/tasks/opaque%2Fid%20%26%20one",
        )
        self.assertEqual(
            collection["_links"]["next"]["href"],
            "/deploy/api/v1/tasks?page=3&pageSize=1&filters=Work&filters=Home&algorithm=EDF&heuristic=Slack&search=two%20words",
        )
        self.assertEqual(embedded["description"], "Write report")
        self.assertEqual(embedded["heuristics"][0]["value"], 2.5)
        self.assertEqual(
            resources.task_resource(make_task("."), extended=False)["_links"]["self"]["href"],
            "/deploy/api/v1/tasks/%2E",
        )
        self.assertEqual(
            resources.task_resource(make_task(".."), extended=False)["_links"]["self"]["href"],
            "/deploy/api/v1/tasks/%2E%2E",
        )

    def test_date_values_use_the_configured_zone_and_publish_exact_input_constraints(self) -> None:
        task = make_task()
        task.setStart(TimePoint(datetime.datetime(2026, 11, 1, 1, 30)))
        application = FakeApplication(task)
        resources = ApiResources(cast(Any, application))
        previous_timezone = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        try:
            document = resources.read_task(task.getTaskUID())
            self.assertEqual(document["timeZone"], "America/New_York")
            self.assertEqual(document["start"], "2026-11-01T01:30:00-04:00")
        finally:
            if previous_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_timezone

        actions = {action["name"]: action for action in document["actions"]}
        effort_delta = actions["edit-task"]["inputs"]["effortDelta"]
        self.assertEqual(effort_delta["oneOf"][1]["properties"]["unit"]["const"], "pomodoro")
        self.assertTrue(actions["record-work"]["inputs"]["duration"]["oneOf"][0]["pattern"])
        self.assertTrue(
            actions["edit-task"]["inputs"]["changes"]["properties"]["severity"]["finite"]
        )

    def test_task_detail_is_complete_normalized_and_does_not_mutate_model(self) -> None:
        task = make_task(status="x")
        original = (
            task.getDescription(),
            task.getContext(),
            task.getStart().as_int(),
            task.getDue().as_int(),
            task.getEventRaised(),
            task.getEventWaited(),
            task.getStatus(),
        )
        resources = ApiResources(cast(Any, FakeApplication(task)))

        document = resources.read_task(task.getTaskUID())

        self.assertEqual(document["description"], "Write report")
        self.assertEqual(document["context"], "work")
        self.assertEqual(document["status"], "completed")
        self.assertEqual(document["project"], "Current Project")
        self.assertEqual(document["waited"], " review ")
        self.assertEqual(document["raised"], " release ")
        self.assertEqual(document["totalCost"], {"value": "2.0", "unit": "pomodoro"})
        self.assertEqual(document["investedEffort"], {"value": "1.0", "unit": "pomodoro"})
        self.assertEqual(document["heuristics"], [{
            "name": "Slack",
            "value": 2.5,
            "comment": "Days available",
        }])
        self.assertIsInstance(datetime.datetime.fromisoformat(document["start"]).utcoffset(), datetime.timedelta)
        self.assertIsInstance(datetime.datetime.fromisoformat(document["due"]).utcoffset(), datetime.timedelta)
        self.assertNotIn("complete-task", [action["name"] for action in document["actions"]])
        self.assertEqual(
            original,
            (
                task.getDescription(),
                task.getContext(),
                task.getStart().as_int(),
                task.getDue().as_int(),
                task.getEventRaised(),
                task.getEventWaited(),
                task.getStatus(),
            ),
        )

    def test_non_finite_task_heuristic_is_rejected(self) -> None:
        task = make_task()
        application = FakeApplication(task)
        application.heuristic_value = float("inf")
        resources = ApiResources(cast(Any, application))

        with self.assertRaises(DomainCalculationError):
            resources.read_task(task.getTaskUID())

    def test_operation_receipt_represents_captured_result_without_replaying_it(self) -> None:
        task = make_task()
        application = FakeApplication(task)
        resources = ApiResources(cast(Any, application), "/prefix/api/v1")
        result = OperationResult(
            "record-work",
            OperationTarget("task", task.getTaskUID()),
            value=task,
            affected_ids=(task.getTaskUID(),),
        )
        intent = OperationIntent(
            "record-work",
            OperationTarget("task", task.getTaskUID()),
            {"duration": "30m", "total_cost": "1.5p"},
        )
        receipt = OperationReceipt(
            "0f3a1d52-5c12-4960-a690-4b7f4535dcb3",
            intent,
            "succeeded",
            result=result,
        )

        document = resources.operation_resource(receipt)

        self.assertEqual(document["status"], "succeeded")
        self.assertEqual(
            document["parameters"],
            {"duration": "30m", "totalCost": {"value": "1.52", "unit": "pomodoro"}},
        )
        self.assertEqual(document["result"]["affectedIds"], [task.getTaskUID()])
        self.assertEqual(document["result"]["value"]["id"], task.getTaskUID())
        self.assertEqual(application.operation_executions, 0)

    def test_failure_receipt_keeps_typed_write_evidence_without_local_paths(self) -> None:
        resources = ApiResources(cast(Any, FakeApplication(make_task())), "/api/v1")
        failure = OperationFailure(
            error_type="src.domain.errors.OperationFailedError",
            message="write failed at /private/path",
            effects_state="partial",
            code="operation-failed",
            details={
                "resource": "task",
                "saved_ids": '["task-1"]',
                "saved_count": "1",
                "failed_id": "task-2",
                "write_phase": "replace",
                "path": "/private/path",
                "token": "secret",
            },
            context={"path": "/private/path", "phase": "replace"},
        )
        receipt = OperationReceipt(
            "c2d5c8f9-f25b-4dc3-83ce-4190e2451c4b",
            OperationIntent("create-task", OperationTarget("tasks"), {}),
            "failed",
            failure=failure,
        )

        document = resources.operation_resource(receipt)
        evidence = document["failure"]["details"]

        self.assertEqual(evidence["savedIds"], ["task-1"])
        self.assertEqual(evidence["savedCount"], 1)
        self.assertEqual(evidence["writePhase"], "replace")
        self.assertEqual(len(document["failure"]["_links"]["resources"]), 2)
        self.assertNotIn("path", evidence)
        self.assertNotIn("token", evidence)
        self.assertNotIn("/private/path", str(document))


if __name__ == "__main__":
    unittest.main()
