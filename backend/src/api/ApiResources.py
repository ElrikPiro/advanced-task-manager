"""HAL representations for the task manager's resource-oriented API."""

from __future__ import annotations

import datetime
import json
import math
import os
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.MutationCoordinator import OperationFailure, OperationReceipt
from src.api.ProblemDetails import safe_detail
from src.Utils import (
    ActiveFilterEntry,
    EventStatistics,
    FilterEntry,
    TaskEntry,
    TaskHeuristicsInfo,
    WorkLogEntry,
)
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import (
    AmbiguousResourceError,
    DomainCalculationError,
    InvalidResourceDataError,
    ResourceReadError,
)
from src.domain.models import (
    AgendaQuery,
    OperationIntent,
    OperationResult,
    OperationTarget,
    ProjectMutationResult,
    TaskView,
)
from src.Interfaces.ITaskModel import ITaskModel
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class ApiResources:
    """Build prefix-aware HAL documents from read-only application results."""

    def __init__(
        self,
        application_service: TaskApplicationService,
        prefix: str = "/api/v1",
        token: str = "",
        notification_history_store: Any | None = None,
    ) -> None:
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError("API prefix must be a non-empty path")
        parsed_prefix = urlsplit(prefix)
        if parsed_prefix.scheme or parsed_prefix.netloc or parsed_prefix.query or parsed_prefix.fragment:
            raise ValueError("API prefix must be a path without query or fragment")
        self.application_service = application_service
        self._diagnostic_token = token
        self.notification_history_store = notification_history_store
        self.prefix = "/" + "/".join(part for part in prefix.split("/") if part)
        if self.prefix == "/":
            raise ValueError("API prefix must include a version path")

    def read_root(self) -> dict[str, Any]:
        """Return the API entry point and its collection relationships."""
        links = {
            "self": self._link(self.prefix),
            "tasks": self._link(self._href("tasks")),
            "agenda": self._link(self._href("agenda")),
            "statistics": self._link(self._href("statistics")),
            "events": self._link(self._href("events")),
            "status": self._link(self._href("status")),
            "strategies": self._link(self._href("strategies")),
            "projects": self._link(self._href("projects")),
            "operations": self._link(self._href("operations"), method="POST"),
        }
        if self.notification_history_store is not None:
            links["notifications"] = self._link(self._href("notifications"))
        return {
            "version": "1",
            "timeZone": self._time_zone_name(),
            "_links": links,
        }

    def read_status(self) -> dict[str, Any]:
        """Expose readiness and refresh age without exposing provider paths."""
        status = self.application_service.read_service_status()
        ready = status.get("ready")
        refreshing = status.get("refreshing")
        generation = status.get("generation")
        age = status.get("snapshot_age_seconds")
        if not isinstance(ready, bool) or not isinstance(refreshing, bool):
            raise ResourceReadError("Service status could not be read")
        if generation is not None and (
            isinstance(generation, bool) or not isinstance(generation, int) or generation < 0
        ):
            raise ResourceReadError("Service status could not be read")
        if age is not None:
            age = self._finite_number(age, "snapshot age")
            if age < 0:
                age = 0.0
        built_at = self._status_timestamp(status.get("built_at"))
        last_success = self._status_timestamp(status.get("last_success"))
        last_error = status.get("last_error")
        if last_error is not None and not isinstance(last_error, str):
            raise ResourceReadError("Service status could not be read")
        local_day = status.get("local_day")
        if local_day is not None and not isinstance(local_day, str):
            raise ResourceReadError("Service status could not be read")
        return {
            "ready": ready,
            "generation": generation,
            "builtAt": built_at,
            "snapshotAgeSeconds": age,
            "localDay": local_day,
            "refreshing": refreshing,
            "lastSuccess": last_success,
            "lastError": safe_detail(last_error, self._diagnostic_token) if last_error else None,
            "observedAt": self._now_iso(),
            "_links": {
                "self": self._link(self._href("status")),
                "root": self._link(self.prefix),
            },
        }

    def read_notifications(self) -> dict[str, Any]:
        """Return the full saved notification history without consuming it."""
        store = self.notification_history_store
        if store is None:
            raise ResourceReadError("Notification history is not configured")
        snapshot = store.read()
        snapshot_data = snapshot.to_dict()
        if not isinstance(snapshot_data, Mapping):
            raise ResourceReadError("Notification history could not be read")

        schema_version = snapshot_data.get("schemaVersion")
        history_id = snapshot_data.get("historyId")
        next_sequence = snapshot_data.get("nextSequence")
        discarded_through = snapshot_data.get("discardedThrough")
        entries = snapshot_data.get("entries")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ResourceReadError("Notification history could not be read")
        if schema_version < 1:
            raise ResourceReadError("Notification history could not be read")
        if not isinstance(history_id, str) or not history_id:
            raise ResourceReadError("Notification history could not be read")
        if isinstance(next_sequence, bool) or not isinstance(next_sequence, int):
            raise ResourceReadError("Notification history could not be read")
        if next_sequence < 1:
            raise ResourceReadError("Notification history could not be read")
        if isinstance(discarded_through, bool) or not isinstance(discarded_through, int):
            raise ResourceReadError("Notification history could not be read")
        if discarded_through < 0:
            raise ResourceReadError("Notification history could not be read")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise ResourceReadError("Notification history could not be read")

        notifications: list[dict[str, Any]] = []
        previous_sequence = 0
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ResourceReadError("Notification history could not be read")
            sequence = entry.get("sequence")
            timestamp = entry.get("timestamp")
            text = entry.get("text")
            if isinstance(sequence, bool) or not isinstance(sequence, int):
                raise ResourceReadError("Notification history could not be read")
            if sequence <= previous_sequence or sequence >= next_sequence:
                raise ResourceReadError("Notification history could not be read")
            if not isinstance(timestamp, str) or not isinstance(text, str):
                raise ResourceReadError("Notification history could not be read")
            try:
                parsed_timestamp = datetime.datetime.fromisoformat(timestamp)
            except ValueError as error:
                raise ResourceReadError("Notification history could not be read") from error
            if parsed_timestamp.tzinfo is None:
                raise ResourceReadError("Notification history could not be read")
            expected_id = f"{history_id}:{sequence}"
            if entry.get("id") != expected_id:
                raise ResourceReadError("Notification history could not be read")
            notifications.append({
                "id": expected_id,
                "historyId": history_id,
                "sequence": sequence,
                "timestamp": timestamp,
                "text": safe_detail(text, self._diagnostic_token),
            })
            previous_sequence = sequence

        if len(notifications) > 1024:
            raise ResourceReadError("Notification history could not be read")
        sequences = [item["sequence"] for item in notifications]
        return {
            "schemaVersion": schema_version,
            "historyId": history_id,
            "nextSequence": next_sequence,
            "discardedThrough": discarded_through,
            "retainedFromSequence": sequences[0] if sequences else None,
            "retainedThroughSequence": sequences[-1] if sequences else None,
            "total": len(notifications),
            "observedAt": self._now_iso(),
            "_links": {
                "self": self._link(self._href("notifications")),
                "root": self._link(self.prefix),
            },
            "_embedded": {"notifications": notifications},
        }

    def read_tasks(self, view: TaskView) -> dict[str, Any]:
        """Return a live page of full task resources and query relationships."""
        snapshot = self._read_task_projection_snapshot()
        task_models: list[ITaskModel] | None
        if snapshot is not None:
            task_models = self.application_service.task_models_from_snapshot(snapshot)
            content = self.application_service.query_tasks(view, task_models=task_models)
        else:
            task_models = self._read_task_projection_models()
        if snapshot is None and task_models is None:
            content = self.application_service.query_tasks(view)
            task_models = self.application_service.read_task_models(include_completed=True)
        elif snapshot is None:
            content = self.application_service.query_tasks(view, task_models=task_models)
        models_by_id: dict[str, ITaskModel] | None = None
        if snapshot is None or not callable(getattr(snapshot, "getTaskById", None)):
            if task_models is None:
                raise DomainCalculationError("The task query did not provide its source models")
            models_by_id = self._unique_tasks_by_id(task_models)
        embedded_tasks: list[dict[str, Any]] = []
        for entry in content.tasks:
            task = (
                self.application_service.read_task_from_snapshot(entry.id, snapshot)
                if snapshot is not None and models_by_id is None
                else models_by_id.get(entry.id) if models_by_id is not None else None
            )
            if task is None:
                raise DomainCalculationError("A task view referenced an unavailable task")
            heuristic_value = self._finite_number(entry.heuristic_value, "heuristic value")
            embedded_tasks.append(
                self.task_resource(
                    task,
                    extended=False,
                    heuristic_name=content.sort_heuristic,
                    heuristic_value=heuristic_value,
                )
            )

        links: dict[str, Any] = {
            "self": self._link(self._query_href("tasks", self._view_query(view))),
            "root": self._link(self.prefix),
            "first": self._link(self._query_href("tasks", self._view_query(view, page=1))),
        }
        if content.current_page > 1:
            links["prev"] = self._link(
                self._query_href("tasks", self._view_query(view, page=content.current_page - 1))
            )
        if content.current_page < content.total_pages:
            links["next"] = self._link(
                self._query_href("tasks", self._view_query(view, page=content.current_page + 1))
            )

        return {
            "total": content.total_tasks,
            "page": content.current_page,
            "pageSize": view.page_size,
            "totalPages": content.total_pages,
            "algorithm": {"name": content.algorithm_name, "description": content.algorithm_desc},
            "heuristic": content.sort_heuristic,
            "filters": [self._filter_representation(item) for item in content.active_filters],
            "search": list(view.search),
            "observedAt": self._now_iso(),
            "actions": [self._create_task_action()],
            "_links": links,
            "_embedded": {"tasks": embedded_tasks},
        }

    def read_task(self, task_id: str) -> dict[str, Any]:
        """Read a task by opaque ID, including its computed detail fields."""
        if isinstance(self.application_service, TaskApplicationService):
            # A detail request needs only the provider's indexed identity lookup.
            # The returned model carries metadata from that same published
            # generation, so detail does not materialize every task model.
            task = self.application_service.read_task(task_id)
            task_models = None
        else:
            task_models = self._read_task_projection_models()
            if task_models is None:
                task = self.application_service.read_task(task_id)
            else:
                task = self.application_service.read_task(task_id, task_models=task_models)
        return self.task_resource(task, extended=True, task_models=task_models)

    def task_resource(
        self,
        task: ITaskModel,
        *,
        extended: bool = True,
        heuristic_name: str | None = None,
        heuristic_value: float | None = None,
        task_models: Sequence[ITaskModel] | None = None,
    ) -> dict[str, Any]:
        """Serialize one already-resolved task model without resolving it again."""
        try:
            task_id = task.getTaskUID()
            if not isinstance(task_id, str) or not task_id:
                raise InvalidResourceDataError("Task identifier is invalid")
            start = self._point_iso(task.getStart())
            due = self._point_iso(task.getDue())
            raw_description = self._raw_description(task)
            context = task.getContext()
            if not isinstance(context, str):
                raise InvalidResourceDataError("Task context is invalid")
            context = context.strip()
            project = self._optional_text(task.getProject(), "project")
            waited = self._optional_text(task.getEventWaited(), "waited")
            raised = self._optional_text(task.getEventRaised(), "raised")
            calm = task.getCalm()
            if not isinstance(calm, bool):
                raise InvalidResourceDataError("Task calm value is invalid")
            status = self._status(task.getStatus())
            task_document: dict[str, Any] = {
                "id": task_id,
                "timeZone": self._time_zone_name(),
                "description": raw_description,
                "context": context,
                "start": start,
                "due": due,
                "severity": self._finite_number(task.getSeverity(), "severity"),
                "totalCost": self._amount(task.getTotalCost()),
                "investedEffort": self._amount(task.getInvestedEffort()),
                "status": status,
                "calm": calm,
                "project": project,
                "waited": waited,
                "raised": raised,
                "observedAt": self._now_iso(),
                "heuristics": [],
                "metadata": None,
                "_links": {
                    "self": self._link(self._href(f"tasks/{self._segment(task_id)}")),
                    "collection": self._link(self._href("tasks")),
                    "root": self._link(self.prefix),
                },
                "actions": self._task_actions(task_id, status=status),
            }
            if heuristic_name and heuristic_name != "None" and heuristic_value is not None:
                task_document["heuristicValue"] = self._finite_number(
                    heuristic_value,
                    "heuristic value",
                )
                task_document["heuristics"] = [{
                    "name": heuristic_name,
                    "value": task_document["heuristicValue"],
                    "comment": "",
                }]
            if extended:
                if task_models is None:
                    detail = self.application_service.read_task_information_for(task, extended=True)
                else:
                    detail = self.application_service.read_task_information_for(
                        task,
                        extended=True,
                        task_models=task_models,
                    )
                task_document["heuristics"] = [
                    self._heuristic_representation(item)
                    for item in (detail.extended.heuristics if detail.extended is not None else [])
                ]
                task_document["metadata"] = self._task_metadata(task_document)
            return task_document
        except DomainCalculationError:
            raise
        except InvalidResourceDataError:
            raise
        except Exception as error:
            raise DomainCalculationError("Task representation could not be calculated") from error

    def read_agenda(self, query: AgendaQuery) -> dict[str, Any]:
        """Return the requested civil-day agenda with direct task links."""
        snapshot = self._read_task_projection_snapshot()
        task_models: list[ITaskModel] | None
        if snapshot is not None:
            task_models = self.application_service.task_models_from_snapshot(snapshot)
            agenda = self.application_service.read_agenda(query, task_models=task_models)
        else:
            task_models = self._read_task_projection_models()
        if snapshot is None and task_models is None:
            agenda = self.application_service.read_agenda(query)
            task_models = self.application_service.read_task_models(include_completed=True)
        elif snapshot is None:
            agenda = self.application_service.read_agenda(query, task_models=task_models)
        models_by_id: dict[str, ITaskModel] | None = None
        if snapshot is None or not callable(getattr(snapshot, "getTaskById", None)):
            if task_models is None:
                raise DomainCalculationError("The agenda did not provide its source models")
            models_by_id = self._unique_tasks_by_id(task_models)

        active = self._agenda_entries(agenda.active_urgent_tasks, models_by_id, snapshot)
        planned = self._agenda_entries(agenda.planned_urgent_tasks, models_by_id, snapshot)
        other = self._agenda_entries(agenda.other_tasks, models_by_id, snapshot)
        planned_groups: dict[str, list[dict[str, Any]]] = {}
        for resource in planned:
            start = resource["start"]
            if not isinstance(start, str):
                raise DomainCalculationError("Agenda task start is invalid")
            civil_day = datetime.datetime.fromisoformat(start).date().isoformat()
            planned_groups.setdefault(civil_day, []).append(resource)

        day = agenda.date.datetime_representation.date().isoformat()
        return {
            "day": day,
            "timeZone": self._time_zone_name(),
            "heuristic": query.heuristic,
            "observedAt": self._now_iso(),
            "_links": {
                "self": self._link(self._query_href("agenda", [("day", day), ("heuristic", query.heuristic)])),
                "root": self._link(self.prefix),
                "tasks": self._link(self._href("tasks")),
            },
            "_embedded": {
                "activeUrgentTasks": active,
                "plannedUrgentTasks": planned,
                "plannedTasksByDate": planned_groups,
                "otherTasks": other,
            },
        }

    def read_statistics(self, view: TaskView) -> dict[str, Any]:
        """Return work and workload data calculated from the current query set."""
        snapshot = self._read_task_projection_snapshot()
        task_models: list[ITaskModel] | None
        if snapshot is not None:
            task_models = self.application_service.task_models_from_snapshot(snapshot)
            combined_reader = getattr(
                self.application_service,
                "read_statistics_and_task_query",
                None,
            )
            if callable(combined_reader):
                stats, content = combined_reader(view, task_models=task_models)
            else:
                stats = self.application_service.read_statistics(view, task_models=task_models)
                content = self.application_service.query_tasks(view, task_models=task_models)
        else:
            task_models = self._read_task_projection_models()
        if snapshot is None and task_models is None:
            stats = self.application_service.read_statistics(view)
            content = self.application_service.query_tasks(view)
        elif snapshot is None:
            stats = self.application_service.read_statistics(view, task_models=task_models)
            content = self.application_service.query_tasks(view, task_models=task_models)
        work_done = {
            day: self._finite_number(value, "work done")
            for day, value in stats.workDone.items()
        }
        work_log = [self._work_log_representation(entry) for entry in stats.workDoneLog]
        return {
            "taskCount": content.total_tasks,
            "timeZone": self._time_zone_name(),
            "workload": self._amount(stats.workload),
            "remainingEffort": self._amount(stats.remainingEffort),
            "slack": {
                "name": stats.HeuristicName,
                "value": self._finite_number(stats.maxHeuristic, "slack"),
            },
            "offender": stats.offender,
            "offenderWorkload": self._amount(stats.offenderMax),
            "workDone": work_done,
            "workDoneLog": work_log,
            "observedAt": self._now_iso(),
            "_links": {
                "self": self._link(self._query_href("statistics", self._view_query(view, include_page=False))),
                "root": self._link(self.prefix),
                "tasks": self._link(self._query_href("tasks", self._view_query(view))),
            },
        }

    def read_events(self) -> dict[str, Any]:
        """Return event totals and rows for noncompleted tasks."""
        content = self.application_service.read_events()
        event_rows = [self._event_representation(item) for item in content.event_statistics]
        return {
            "totalEvents": content.total_events,
            "timeZone": self._time_zone_name(),
            "totalRaisingTasks": content.total_raising_tasks,
            "totalWaitingTasks": content.total_waiting_tasks,
            "orphanedEvents": content.orphaned_events_count,
            "observedAt": self._now_iso(),
            "actions": [self._raise_event_action()],
            "_links": {
                "self": self._link(self._href("events")),
                "root": self._link(self.prefix),
            },
            "_embedded": {"events": event_rows},
        }

    def read_strategies(self) -> dict[str, Any]:
        """Return filters and strategy descriptions without selecting any of them."""
        content = self.application_service.read_strategies()
        filters = [self._catalog_item(item, kind="filter") for item in content["filters"]]
        algorithms = [self._catalog_item(item, kind="algorithm") for item in content["algorithms"]]
        heuristics = [self._catalog_item(item, kind="heuristic") for item in content["heuristics"]]
        return {
            "timeZone": self._time_zone_name(),
            "observedAt": self._now_iso(),
            "_links": {
                "self": self._link(self._href("strategies")),
                "root": self._link(self.prefix),
            },
            "_embedded": {
                "filters": filters,
                "algorithms": algorithms,
                "heuristics": heuristics,
            },
        }

    def read_projects(self, status: str = "open") -> dict[str, Any]:
        """Return a project collection and only the actions supported by storage."""
        projects = self.application_service.read_projects(status)
        resources = [self.project_resource(project) for project in projects]
        query = [("status", status)]
        return {
            "status": status,
            "timeZone": self._time_zone_name(),
            "total": len(resources),
            "observedAt": self._now_iso(),
            "actions": self._project_actions(None),
            "_links": {
                "self": self._link(self._query_href("projects", query)),
                "root": self._link(self.prefix),
            },
            "_embedded": {"projects": resources},
        }

    def read_project(self, name: str) -> dict[str, Any]:
        """Read a project by its decoded name."""
        project = self.application_service.read_project(name)
        return self.project_resource(project)

    def project_resource(self, project: Mapping[str, Any] | ProjectMutationResult) -> dict[str, Any]:
        """Serialize a project summary or operation snapshot without its file path."""
        if isinstance(project, ProjectMutationResult):
            result: dict[str, Any] = {
                "name": project.name,
                "status": project.status,
            }
            if project.description is not None:
                result["description"] = project.description
            if project.content is not None:
                result["content"] = project.content
        else:
            result = {
                "name": project.get("name"),
                "status": project.get("status"),
            }
            if "description" in project:
                result["description"] = project.get("description")
            if "content" in project:
                result["content"] = project.get("content")
        name = result.get("name")
        status = result.get("status")
        project_name: Any = result.get("name")
        project_status: Any = result.get("status")
        if not isinstance(project_name, str) or not project_name or not isinstance(project_status, str):
            raise InvalidResourceDataError("Project representation is invalid")
        name = project_name
        status = project_status
        result["observedAt"] = self._now_iso()
        result["timeZone"] = self._time_zone_name()
        result["_links"] = {
            "self": self._link(self._href(f"projects/{self._segment(name)}")),
            "collection": self._link(self._href("projects")),
            "root": self._link(self.prefix),
        }
        result["actions"] = self._project_actions(name, status=status)
        return result

    def read_operation(self, operation_id: str) -> dict[str, Any]:
        """Represent a retained operation result without submitting or replaying it."""
        receipt = self.application_service.get_operation_receipt(operation_id)
        return self.operation_resource(receipt)

    def operation_resource(self, receipt: OperationReceipt) -> dict[str, Any]:
        """Serialize an immutable in-memory receipt and its captured result."""
        if not isinstance(receipt, OperationReceipt):
            raise InvalidResourceDataError("Operation receipt is invalid")
        operation_id = receipt.operation_id
        intent = receipt.intent
        if isinstance(intent, OperationIntent):
            operation_type = intent.operation_type
            target = intent.target
            parameters = intent.parameters
        else:
            operation_type = "unknown"
            target = OperationTarget("tasks")
            parameters = {}

        result = receipt.result
        result_document: dict[str, Any] | None = None
        failure_document: dict[str, Any] | None = None
        if isinstance(result, OperationResult):
            result_document = self._operation_result_representation(result)
        failure = receipt.failure
        if isinstance(failure, OperationFailure):
            failure_document = self._operation_failure_representation(failure, target)

        return {
            "id": operation_id,
            "status": receipt.status,
            "type": operation_type,
            "target": self._target_representation(target),
            "parameters": self._public_parameters(parameters),
            "result": result_document,
            "failure": failure_document,
            "timeZone": self._time_zone_name(),
            "observedAt": self._now_iso(),
            "_links": {
                "self": self._link(self._href(f"operations/{self._segment(operation_id)}")),
                "root": self._link(self.prefix),
            },
            "_embedded": {"results": [] if result_document is None else [result_document]},
        }

    def _task_actions(self, task_id: str, *, status: str = "open") -> list[dict[str, Any]]:
        target = {"kind": "task", "id": task_id}
        context_input: dict[str, Any] = {"type": "string", "required": False}
        read_context_prefixes = getattr(self.application_service, "task_context_prefixes", None)
        context_prefixes = read_context_prefixes() if callable(read_context_prefixes) else ()
        context_input["startsWithAny"] = list(context_prefixes)
        edit_fields = {
            "description": {"type": "string", "required": False, "minLength": 1},
            "context": context_input,
            "start": self._date_input("start"),
            "due": self._date_input("due"),
            "severity": {"type": "number", "required": False, "finite": True},
            "totalCost": self._pomodoro_object_input(required=False),
            "calm": {"type": "boolean", "required": False},
            "raised": {"type": ["string", "null"], "required": False},
            "waited": {"type": ["string", "null"], "required": False},
        }
        actions = [
            self._action(
                "edit-task",
                target,
                {
                    "changes": {"type": "object", "required": False, "properties": edit_fields},
                    "effortDelta": self._duration_input(
                        required=False,
                        allow_pomodoro_object=True,
                    ),
                },
            ),
            self._action(
                "schedule-task",
                target,
                {"effortPerDay": self._duration_input(required=False, allow_number=True)},
            ),
            self._action(
                "record-work",
                target,
                {"duration": self._duration_input(required=True)},
            ),
            self._action(
                "snooze-task",
                target,
                {"duration": self._duration_input(required=False, default="5m")},
            ),
        ]
        if status != "completed":
            actions.insert(1, self._action("complete-task", target, {}))
        read_scheduling = getattr(self.application_service, "scheduling_preview_configuration", None)
        configuration = read_scheduling() if callable(read_scheduling) else None
        if isinstance(configuration, Mapping) and configuration.get("algorithm") == "heuristic-v1":
            dedication = self._finite_number(configuration.get("dailyDedication"), "daily dedication")
            for action in actions:
                if action["name"] == "schedule-task":
                    action["preview"] = {"algorithm": "heuristic-v1", "dailyDedication": dedication}
        return actions

    def _create_task_action(self) -> dict[str, Any]:
        return self._action(
            "create-task",
            {"kind": "tasks"},
            {
                "description": {"type": "string", "required": True, "minLength": 1},
                "context": {
                    "type": "string", "required": False, "requiredWith": "totalCost",
                    "startsWithAny": list(self.application_service.task_context_prefixes())
                    if callable(getattr(self.application_service, "task_context_prefixes", None)) else [],
                },
                "totalCost": self._pomodoro_object_input(required=False, required_with="context"),
            },
        )

    def _raise_event_action(self, event_name: str | None = None) -> dict[str, Any]:
        target: dict[str, Any] = {"kind": "event"}
        inputs: dict[str, Any] = {}
        if event_name is None:
            inputs["target.id"] = {"type": "string", "required": True, "minLength": 1}
        else:
            target["id"] = event_name
        return self._action("raise-event", target, inputs)

    @staticmethod
    def _pomodoro_object_input(
        *,
        required: bool,
        required_with: str | None = None,
    ) -> dict[str, Any]:
        descriptor: dict[str, Any] = {
            "type": "object",
            "required": required,
            "requiredKeys": ["value", "unit"],
            "additionalProperties": False,
            "properties": {
                "value": {
                    "type": "string",
                    "format": "decimal",
                    "pattern": r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
                    "maxLength": 64,
                },
                "unit": {"type": "string", "const": "pomodoro"},
            },
        }
        if required_with is not None:
            descriptor["requiredWith"] = required_with
        return descriptor

    @classmethod
    def _duration_input(
        cls,
        *,
        required: bool,
        allow_pomodoro_object: bool = False,
        allow_number: bool = False,
        default: str | None = None,
    ) -> dict[str, Any]:
        expression: dict[str, Any] = {
            "type": "string",
            "format": "time-amount",
            "pattern": r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)[dhmpsw]$|^[+-]?[0-9]+:[0-9]+$",
            "units": ["d", "h", "m", "p", "s", "w"],
            "clockFormat": "HH:MM",
        }
        alternatives: list[dict[str, Any]] = [expression]
        if allow_pomodoro_object:
            alternatives.append(cls._pomodoro_object_input(required=True))
        if allow_number:
            alternatives.append({"type": "number", "finite": True, "unit": "pomodoro"})
        descriptor: dict[str, Any] = {
            "type": "duration",
            "required": required,
            "oneOf": alternatives,
        }
        if default is not None:
            descriptor["default"] = default
        return descriptor

    @staticmethod
    def _date_input(field: str) -> dict[str, Any]:
        return {
            "type": "string",
            "required": False,
            "format": "date-time",
            "offsetRequired": True,
            "relativeExpressions": {
                "forms": ["+duration", "-duration", "today", "tomorrow", "HH:MM"],
                "componentsSeparatedBy": ";",
                "nowAllowed": field == "start",
                "durationUnits": ["d", "h", "m", "p", "s", "w"],
            },
            "legacyForms": ["YYYY-MM-DD", "YYYY-MM-DDTHH:MM"],
        }

    def _project_actions(self, name: str | None, *, status: str | None = None) -> list[dict[str, Any]]:
        capabilities = self.application_service.project_operation_capabilities()
        actions: list[dict[str, Any]] = []
        for operation_type, inputs in capabilities.items():
            if name is None and operation_type != "open-project":
                continue
            if name is not None and operation_type == "open-project" and status == "open":
                continue
            if name is not None and operation_type in {"close-project", "hold-project"} and status != "open":
                continue
            target: dict[str, Any] = {"kind": "project"}
            public_inputs: dict[str, Any] = {}
            for field, definition in inputs.items():
                if field == "target.id":
                    if name is None:
                        public_inputs[field] = definition
                    else:
                        target["id"] = name
                else:
                    public_inputs[field] = definition
            if name is not None:
                target["id"] = name
            actions.append(self._action(operation_type, target, public_inputs))
        return actions

    def _action(
        self,
        name: str,
        target: Mapping[str, Any],
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "name": name,
            "href": self._href("operations"),
            "method": "POST",
            "contentType": "application/json",
            "target": dict(target),
            "inputs": dict(inputs),
        }

    def _agenda_entries(
        self,
        entries: Sequence[TaskEntry],
        models_by_id: Mapping[str, ITaskModel] | None,
        snapshot: Any | None = None,
    ) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        for entry in entries:
            task = (
                self.application_service.read_task_from_snapshot(entry.id, snapshot)
                if snapshot is not None and models_by_id is None
                else models_by_id.get(entry.id) if models_by_id is not None else None
            )
            if task is None:
                raise DomainCalculationError("An agenda referenced an unavailable task")
            resources.append(
                self.task_resource(
                    task,
                    extended=False,
                    heuristic_value=self._finite_number(entry.heuristic_value, "heuristic value"),
                )
            )
        return resources

    @staticmethod
    def _unique_tasks_by_id(tasks: Sequence[ITaskModel]) -> dict[str, ITaskModel]:
        result: dict[str, ITaskModel] = {}
        for task in tasks:
            task_id = task.getTaskUID()
            if task_id in result:
                raise AmbiguousResourceError("More than one task has the same identifier")
            result[task_id] = task
        return result

    def _read_task_projection_snapshot(self) -> Any | None:
        """Capture a generation-bound task view for application projections."""
        if isinstance(self.application_service, TaskApplicationService):
            return self.application_service.read_task_snapshot()
        return None

    def _read_task_projection_models(self) -> list[ITaskModel] | None:
        """Load one request-local model set for non-standard application adapters."""
        if isinstance(self.application_service, TaskApplicationService):
            return self.application_service.read_task_models(include_completed=True)
        return None

    @staticmethod
    def _status_timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value.isoformat()
        if isinstance(value, str):
            return value
        raise ResourceReadError("Service status could not be read")

    @staticmethod
    def _raw_description(task: ITaskModel) -> str:
        for method_name in ("getRawDescription", "getTaskText"):
            method = getattr(task, method_name, None)
            if callable(method):
                value = method()
                if isinstance(value, str):
                    return value
        value = task.getDescription()
        if not isinstance(value, str):
            raise InvalidResourceDataError("Task description is invalid")
        return value

    @staticmethod
    def _status(value: str) -> str:
        if not isinstance(value, str):
            raise InvalidResourceDataError("Task status is invalid")
        normalized = value.strip().casefold()
        if normalized in {"x", "done", "complete", "completed"}:
            return "completed"
        if normalized in {"", "open", "todo", "incomplete"}:
            return "open"
        raise InvalidResourceDataError("Task status is invalid")

    @staticmethod
    def _optional_text(value: Any, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidResourceDataError(f"Task {field} value is invalid")
        return value if value else None

    @staticmethod
    def _task_metadata(task_document: Mapping[str, Any]) -> dict[str, Any]:
        """Expose an allowlisted snapshot of task-domain metadata."""
        fields = (
            "id",
            "description",
            "context",
            "start",
            "due",
            "severity",
            "totalCost",
            "investedEffort",
            "status",
            "calm",
            "project",
            "waited",
            "raised",
        )
        return {field: task_document[field] for field in fields}

    @staticmethod
    def _finite_number(value: Any, field: str) -> float | int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DomainCalculationError(f"{field.capitalize()} is not numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise DomainCalculationError(f"{field.capitalize()} is not finite")
        return value

    def _amount(self, amount: TimeAmount) -> dict[str, str]:
        pomodoros = self._finite_number(amount.as_pomodoros(), "duration")
        return {"value": str(pomodoros), "unit": "pomodoro"}

    def _point_iso(self, point: TimePoint) -> str:
        value = point.datetime_representation
        if value.tzinfo is None:
            value = value.replace(tzinfo=self._configured_timezone())
        else:
            value = value.astimezone(self._configured_timezone())
        return value.isoformat()

    def _now_iso(self) -> str:
        return datetime.datetime.now(self._configured_timezone()).isoformat()

    def _time_zone_name(self) -> str:
        timezone = self._configured_timezone()
        key = getattr(timezone, "key", None)
        if isinstance(key, str):
            return key
        return datetime.datetime.now(timezone).tzname() or "UTC"

    @staticmethod
    def _configured_timezone() -> datetime.tzinfo:
        configured = os.environ.get("TZ")
        if configured:
            zone_name = configured.removeprefix(":")
            try:
                return ZoneInfo(zone_name)
            except ZoneInfoNotFoundError:
                pass
        localtime_path = os.path.realpath("/etc/localtime")
        zoneinfo_marker = f"{os.sep}zoneinfo{os.sep}"
        zoneinfo_index = localtime_path.rfind(zoneinfo_marker)
        if zoneinfo_index >= 0:
            zone_name = localtime_path[zoneinfo_index + len(zoneinfo_marker):]
            try:
                return ZoneInfo(zone_name)
            except ZoneInfoNotFoundError:
                pass
        timezone = datetime.datetime.now().astimezone().tzinfo
        return timezone if timezone is not None else datetime.timezone.utc

    @staticmethod
    def _link(href: str, *, method: str | None = None) -> dict[str, str]:
        link = {"href": href}
        if method is not None:
            link["method"] = method
        return link

    def _href(self, path: str) -> str:
        suffix = path.lstrip("/")
        return f"{self.prefix}/{suffix}" if suffix else self.prefix

    @staticmethod
    def _segment(value: str) -> str:
        if value == ".":
            return "%2E"
        if value == "..":
            return "%2E%2E"
        return quote(value, safe="")

    def _query_href(self, path: str, query: Sequence[tuple[str, Any]]) -> str:
        encoded = urlencode(list(query), doseq=True, quote_via=quote)
        return f"{self._href(path)}?{encoded}" if encoded else self._href(path)

    @staticmethod
    def _view_query(
        view: TaskView,
        *,
        page: int | None = None,
        include_page: bool = True,
    ) -> list[tuple[str, Any]]:
        query: list[tuple[str, Any]] = []
        if include_page:
            query.append(("page", page if page is not None else view.page))
            query.append(("pageSize", view.page_size))
        query.extend(("filters", value) for value in view.filters)
        if view.algorithm:
            query.append(("algorithm", view.algorithm))
        if view.heuristic:
            query.append(("heuristic", view.heuristic))
        query.extend(("search", value) for value in view.search)
        return query

    @staticmethod
    def _filter_representation(item: ActiveFilterEntry) -> dict[str, Any]:
        return {"name": item.name, "index": item.index, "description": item.description}

    @staticmethod
    def _heuristic_representation(item: TaskHeuristicsInfo) -> dict[str, Any]:
        if not isinstance(item.name, str) or not isinstance(item.comment, str):
            raise InvalidResourceDataError("Task heuristic data is invalid")
        value = ApiResources._finite_number(item.value, "heuristic value")
        return {"name": item.name, "value": value, "comment": item.comment}

    @staticmethod
    def _work_log_representation(entry: WorkLogEntry) -> dict[str, Any]:
        if isinstance(entry.timestamp, bool) or not isinstance(entry.timestamp, int):
            raise InvalidResourceDataError("Work log timestamp is invalid")
        instant = datetime.datetime.fromtimestamp(
            entry.timestamp / 1000,
            tz=ApiResources._configured_timezone(),
        ).isoformat()
        work_units = ApiResources._finite_number(entry.work_units, "work units")
        if not isinstance(entry.task, str):
            raise InvalidResourceDataError("Work log task is invalid")
        return {"timestamp": instant, "workUnits": str(work_units), "unit": "pomodoro", "task": entry.task}

    def _event_representation(self, item: EventStatistics) -> dict[str, Any]:
        return {
            "name": item.event_name,
            "raisingTasks": item.tasks_raising,
            "waitingTasks": item.tasks_waiting,
            "orphaned": item.is_orphaned,
            "orphanType": item.orphan_type,
            "actions": [self._raise_event_action(item.event_name)],
        }

    @staticmethod
    def _catalog_item(item: FilterEntry | Mapping[str, Any], *, kind: str) -> dict[str, Any]:
        if isinstance(item, FilterEntry):
            catalog_name: Any = item.name
            catalog_description: Any = item.description
            enabled: bool | None = item.enabled
        else:
            catalog_name = item.get("name")
            catalog_description = item.get("description")
            enabled_value = item.get("enabled")
            enabled = enabled_value if isinstance(enabled_value, bool) else None
        if not isinstance(catalog_name, str) or not isinstance(catalog_description, str):
            raise InvalidResourceDataError("Strategy catalog entry is invalid")
        name = catalog_name
        description = catalog_description
        result: dict[str, Any] = {"id": name, "name": name, "description": description, "kind": kind}
        if enabled is not None:
            result["enabled"] = enabled
        return result

    @staticmethod
    def _target_representation(target: OperationTarget) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": target.kind}
        if target.id is not None:
            result["id"] = target.id
        return result

    def _operation_result_representation(self, result: OperationResult) -> dict[str, Any]:
        value = result.value
        if isinstance(value, ITaskModel):
            value_document: Any = self.task_resource(value, extended=False)
        elif isinstance(value, ProjectMutationResult):
            value_document = self.project_resource(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            value_document = [self._operation_value(item) for item in value]
        else:
            value_document = self._operation_value(value)
        affected_links: list[dict[str, str]] = []
        for affected_id in result.affected_ids:
            if result.target.kind == "project":
                href = self._href(f"projects/{self._segment(affected_id)}")
            else:
                href = self._href(f"tasks/{self._segment(affected_id)}")
            affected_links.append(self._link(href))
        return {
            "type": result.operation_type,
            "target": self._target_representation(result.target),
            "affectedIds": list(result.affected_ids),
            "effectsState": result.effects_state,
            "value": value_document,
            "_links": {"affected": affected_links},
        }

    def _operation_value(self, value: Any) -> Any:
        if isinstance(value, ITaskModel):
            return self.task_resource(value, extended=False)
        if isinstance(value, ProjectMutationResult):
            return self.project_resource(value)
        if isinstance(value, TimeAmount):
            return self._amount(value)
        if isinstance(value, TimePoint):
            return self._point_iso(value)
        if isinstance(value, Mapping):
            return {str(key): self._operation_value(item) for key, item in value.items()}
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        if isinstance(value, float):
            return self._finite_number(value, "operation result")
        raise InvalidResourceDataError("Operation result cannot be represented")

    def _operation_failure_representation(
        self,
        failure: OperationFailure,
        target: OperationTarget,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {}
        resource_types = {"task", "project", "statistics"}
        for source, destination in (
            ("resource", "resource"),
            ("failed_resource", "failedResource"),
        ):
            value = failure.details.get(source)
            if isinstance(value, str) and value in resource_types:
                details[destination] = value
        for source, destination in (
            ("failed_id", "failedId"),
            ("uncertain_id", "uncertainId"),
        ):
            value = failure.details.get(source)
            if isinstance(value, str) and value:
                details[destination] = safe_detail(value, self._diagnostic_token)

        saved_count = failure.details.get("saved_count")
        if isinstance(saved_count, int) and not isinstance(saved_count, bool) and saved_count >= 0:
            details["savedCount"] = saved_count
        elif isinstance(saved_count, str) and saved_count.isdecimal():
            details["savedCount"] = int(saved_count)

        saved_ids_value = failure.details.get("saved_ids")
        raw_saved_ids: list[str] = []
        if isinstance(saved_ids_value, str):
            try:
                parsed_saved_ids = json.loads(saved_ids_value)
            except (TypeError, ValueError):
                parsed_saved_ids = None
            if isinstance(parsed_saved_ids, list):
                raw_saved_ids = [
                    value for value in parsed_saved_ids
                    if isinstance(value, str) and value
                ]
        elif isinstance(saved_ids_value, list):
            raw_saved_ids = [
                value for value in saved_ids_value
                if isinstance(value, str) and value
            ]
        saved_ids = [
            safe_detail(value, self._diagnostic_token)
            for value in raw_saved_ids
        ]
        if saved_ids:
            details["savedIds"] = saved_ids

        write_phase = failure.details.get("write_phase") or failure.context.get("phase")
        allowed_phases = {
            "compare",
            "temporary_create",
            "write",
            "permissions",
            "flush",
            "file_fsync",
            "temporary_validate",
            "replace",
            "directory_fsync",
        }
        if isinstance(write_phase, str) and write_phase in allowed_phases:
            details["writePhase"] = write_phase
        write_replaced = failure.details.get("write_replaced")
        if isinstance(write_replaced, str) and write_replaced in {"true", "false", "unknown"}:
            details["writeReplaced"] = write_replaced

        review_ids = [
            value for value in raw_saved_ids
            if safe_detail(value, self._diagnostic_token) == value
        ]
        for field in ("failed_id", "uncertain_id"):
            value = failure.details.get(field)
            if isinstance(value, str):
                safe_id = safe_detail(value, self._diagnostic_token)
                if safe_id and safe_id == value and value not in review_ids:
                    review_ids.append(value)
        resource_links = [
            self._link(self._resource_href(target.kind, identifier))
            for identifier in review_ids
        ]
        return {
            "code": safe_detail(
                failure.code or "operation-failed", self._diagnostic_token
            ),
            "detail": "The operation failed; inspect the current resource state.",
            "effectsState": failure.effects_state,
            "details": details,
            "_links": {"resources": resource_links},
        }

    def _resource_href(self, kind: str, identifier: str) -> str:
        if kind == "project":
            return self._href(f"projects/{self._segment(identifier)}")
        return self._href(f"tasks/{self._segment(identifier)}")

    @staticmethod
    def _public_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
        name_map = {
            "total_cost": "totalCost",
            "effort_delta": "effortDelta",
            "effort_per_day": "effortPerDay",
        }
        result: dict[str, Any] = {}
        for key, value in parameters.items():
            public_key = name_map.get(str(key), str(key))
            if key == "total_cost" and isinstance(value, str):
                try:
                    value = TimeAmount(value)
                except Exception as error:
                    raise InvalidResourceDataError(
                        "Operation effort cannot be represented"
                    ) from error
            if isinstance(value, TimePoint):
                result[public_key] = ApiResources._point_iso_value(value)
            elif isinstance(value, TimeAmount):
                amount = value.as_pomodoros()
                result[public_key] = {"value": str(ApiResources._finite_number(amount, "duration")), "unit": "pomodoro"}
            elif isinstance(value, Mapping):
                result[public_key] = ApiResources._public_parameters(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                if isinstance(value, float):
                    result[public_key] = ApiResources._finite_number(value, "operation parameter")
                else:
                    result[public_key] = value
            else:
                raise InvalidResourceDataError("Operation parameters cannot be represented")
        return result

    @staticmethod
    def _point_iso_value(point: TimePoint) -> str:
        value = point.datetime_representation
        timezone = ApiResources._configured_timezone()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone)
        else:
            value = value.astimezone(timezone)
        return value.isoformat()
