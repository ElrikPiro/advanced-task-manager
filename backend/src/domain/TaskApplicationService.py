"""Reusable task reads and operations shared by communication adapters."""

import copy
import datetime
import math
from typing import Any, Mapping

from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.ITaskProvider import ITaskProvider
from src.TelegramTaskListManager import TelegramTaskListManager
from src.Utils import AgendaContent, TaskInformation, TaskListContent
from src.wrappers.TimeManagement import TimeAmount, TimePoint

from .errors import (
    AmbiguousResourceError,
    DomainCalculationError,
    DomainError,
    OperationFailedError,
    ResourceNotFoundError,
    ResourceReadError,
    UnsupportedOperationError,
    ValidationError,
)
from .models import AgendaQuery, OperationResult, OperationTarget, TaskView


class TaskApplicationService:
    """Application boundary with explicit query inputs and typed outcomes.

    Task UIDs still follow the current providers' provisional identity behavior.
    Resolution is not yet persistent; this service never writes an ID merely
    because a task was read.
    """

    _EDIT_FIELDS = {
        "description",
        "context",
        "start",
        "due",
        "severity",
        "total_cost",
        "calm",
        "raised",
        "waited",
    }

    def __init__(
        self,
        task_provider: ITaskProvider,
        scheduling: Any,
        statistics_service: Any,
        task_list_manager: TelegramTaskListManager,
        categories: list[dict[str, str]],
        project_manager: Any | None = None,
    ) -> None:
        self._task_provider = task_provider
        self._scheduling = scheduling
        self._statistics_service = statistics_service
        self._task_list_manager = task_list_manager
        self._categories = categories
        self._project_manager = project_manager

    def _all_tasks(self, *, include_completed: bool = True) -> list[ITaskModel]:
        """Load current provider data without running discovery or maintenance."""
        try:
            return list(self._task_provider.getTaskList(include_completed=include_completed))
        except Exception as error:
            raise ResourceReadError("Task data could not be read") from error

    def discover_initialize(self) -> list[ITaskModel]:
        """Run provider discovery explicitly before a communication listener."""
        discover = getattr(self._task_provider, "discoverTasks", None)
        if not callable(discover):
            return self._all_tasks(include_completed=False)
        try:
            return list(discover())
        except Exception as error:
            raise ResourceReadError("Task discovery failed") from error

    def maintain(self) -> list[ITaskModel]:
        """Expose an explicit maintenance hook for the existing provider cycle."""
        return self.discover_initialize()

    def read_task(self, task_id: str) -> ITaskModel:
        """Read one task by its currently exposed UID, including completed tasks."""
        if not isinstance(task_id, str) or not task_id:
            raise ValidationError("A task identifier is required", details={"field": "id"})
        matches = [task for task in self._all_tasks() if task.getTaskUID() == task_id]
        if not matches:
            raise ResourceNotFoundError("No task matches the requested identifier")
        if len(matches) > 1:
            raise AmbiguousResourceError("More than one task matches the requested identifier")
        return matches[0]

    def query_tasks(self, view: TaskView) -> TaskListContent:
        """Run a task query with its filters, strategies and page supplied inline."""
        self._validate_view(view)
        tasks = self._all_tasks(include_completed=False)
        try:
            manager = self._task_list_manager.clone_for_view(tasks, view)
        except ValueError as error:
            raise ValidationError(str(error), details={"field": "view"}) from error
        try:
            return manager.get_task_list_content()
        except Exception as error:
            raise DomainCalculationError("Task view could not be calculated") from error

    def read_agenda(self, query: AgendaQuery) -> AgendaContent:
        """Calculate an agenda from current tasks and explicit date/heuristic."""
        if not isinstance(query.day, TimePoint):
            raise ValidationError("Agenda day must be a TimePoint", details={"field": "day"})
        tasks = self._all_tasks(include_completed=True)
        try:
            manager = self._task_list_manager.clone_for_view(
                tasks,
                TaskView(heuristic=query.heuristic),
            )
        except ValueError as error:
            raise ValidationError(str(error), details={"field": "heuristic"}) from error
        try:
            return manager.get_day_agenda_content(query.day, self._categories)
        except Exception as error:
            raise DomainCalculationError("Agenda could not be calculated") from error

    def read_task_information(self, task_id: str, *, extended: bool = False) -> TaskInformation:
        """Return typed detail data for a task, independent of list selection."""
        task = self.read_task(task_id)
        try:
            return self._task_list_manager.get_task_information(task, self._task_provider, extended)
        except Exception as error:
            raise ResourceReadError("Task detail could not be read") from error

    def edit_task(self, task_id: str, changes: Mapping[str, Any]) -> ITaskModel:
        """Validate all replacements before saving one copied task model."""
        task = self.read_task(task_id)
        prepared = self._prepare_changes(task, changes)
        candidate = copy.deepcopy(task)
        try:
            self._apply_changes(candidate, prepared)
            self._task_provider.saveTask(candidate)
        except DomainError:
            raise
        except Exception as error:
            raise OperationFailedError(
                "The task could not be saved",
                effects_state="unknown",
                details={"resource": "task"},
            ) from error
        return candidate

    def execute_operation(
        self,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationResult:
        """Execute an explicit supported task operation without UI text."""
        if not isinstance(target, OperationTarget):
            raise ValidationError("Operation target must be typed", details={"field": "target"})
        if not isinstance(parameters, Mapping):
            raise ValidationError("Operation parameters must be an object", details={"field": "parameters"})

        if operation_type == "create-task":
            return self._create_task(target, parameters)
        if operation_type == "edit-task":
            if target.kind != "task" or target.id is None:
                raise ValidationError("edit-task requires a task identifier", details={"field": "target"})
            changes = parameters.get("changes", {})
            unknown = set(parameters) - {"changes", "effort_delta"}
            if unknown:
                raise ValidationError("Unknown edit-task parameter", details={"field": sorted(unknown)[0]})
            if not isinstance(changes, Mapping):
                raise ValidationError("changes must be an object", details={"field": "changes"})
            delta = parameters.get("effort_delta")
            if delta is not None:
                updated = self._edit_task_with_effort_delta(target.id, changes, delta)
            else:
                updated = self.edit_task(target.id, changes)
            return OperationResult(operation_type, target, value=updated, affected_ids=(target.id,))
        if operation_type == "complete-task":
            return self._complete_task(target, parameters)
        if operation_type == "schedule-task":
            return self._schedule_task(target, parameters)
        if operation_type == "record-work":
            return self._record_work(target, parameters)
        if operation_type == "snooze-task":
            return self._snooze_task(target, parameters)
        if operation_type == "raise-event":
            return self._raise_event(target, parameters)
        raise UnsupportedOperationError(f"Unsupported operation type: {operation_type}")

    def _create_task(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        if target.kind not in ("tasks", "task") or target.id is not None:
            raise ValidationError("create-task targets the task collection", details={"field": "target"})
        description = parameters.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValidationError("description is required", details={"field": "description"})
        allowed = {"description", "context", "total_cost"}
        unknown = set(parameters) - allowed
        if unknown:
            raise ValidationError("Unknown create-task parameter", details={"field": sorted(unknown)[0]})
        if ("context" in parameters) != ("total_cost" in parameters):
            raise ValidationError(
                "context and total_cost must be supplied together",
                details={"field": "context"},
            )
        context = parameters.get("context", "inbox")
        cost = parameters.get("total_cost", "1p")
        self._validate_context(context)
        cost_amount = self._as_time_amount(cost, "total_cost")
        try:
            task = self._task_provider.createDefaultTask(description.strip())
            task.setContext(context)
            task.setTotalCost(cost_amount)
            self._task_provider.saveTask(task)
        except DomainError:
            self._discard_pending_task_reservations()
            raise
        except Exception as error:
            self._discard_pending_task_reservations()
            raise OperationFailedError("The new task could not be saved", effects_state="unknown") from error
        task_id = task.getTaskUID()
        return OperationResult("create-task", target, value=task, affected_ids=(task_id,))

    def _complete_task(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        if parameters:
            raise ValidationError("complete-task accepts no parameters", details={"field": "parameters"})
        task = copy.deepcopy(self.read_task(target.id or ""))
        related: list[ITaskModel] = []
        event = task.getEventRaised()
        if isinstance(event, str):
            now = TimePoint.now()
            # The target task may itself await the event it is now raising.
            # It is saved as the completed target below, so update it here and
            # avoid a duplicate save for the same provisional identity.
            if task.getEventWaited() == event:
                task.setEventWaited(None)
                task.setStart(now)
            related = []
            for candidate in self._all_tasks():
                matches_target = candidate.getTaskUID() != target.id
                awaits_event = candidate.getEventWaited() == event
                if matches_target and awaits_event:
                    related.append(copy.deepcopy(candidate))
            for candidate in related:
                candidate.setEventWaited(None)
                candidate.setStart(now)
        task.setStatus("x")
        return self._save_sequential("complete-task", target, [*related, task], value=task)

    def _schedule_task(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        unknown = set(parameters) - {"effort_per_day"}
        if unknown:
            raise ValidationError("Unknown schedule-task parameter", details={"field": sorted(unknown)[0]})
        effort = parameters.get("effort_per_day", "")
        if not isinstance(effort, str):
            raise ValidationError("effort_per_day must be a string", details={"field": "effort_per_day"})
        original = self.read_task(target.id or "")
        task_copy = copy.deepcopy(original)
        try:
            tasks = list(self._scheduling.schedule(task_copy, effort))
        except Exception as error:
            self._discard_pending_task_reservations()
            raise OperationFailedError("The task could not be scheduled", effects_state="none") from error
        if not tasks:
            self._discard_pending_task_reservations()
            raise OperationFailedError("Scheduling produced no tasks", effects_state="none")
        return self._save_sequential("schedule-task", target, tasks, value=tasks)

    def _record_work(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        unknown = set(parameters) - {"duration", "now"}
        if unknown:
            raise ValidationError("Unknown record-work parameter", details={"field": sorted(unknown)[0]})
        duration = self._as_time_amount(parameters.get("duration"), "duration")
        task = copy.deepcopy(self.read_task(target.id or ""))
        task.setInvestedEffort(task.getInvestedEffort() + duration)
        task.setTotalCost(task.getTotalCost() - duration)
        now = parameters.get("now", TimePoint.now())
        if not isinstance(now, TimePoint):
            raise ValidationError("now must be a TimePoint", details={"field": "now"})
        try:
            self._task_provider.saveTask(task)
        except Exception as error:
            raise OperationFailedError("The task could not be saved", effects_state="unknown") from error
        try:
            self._statistics_service.doWork(now.datetime_representation.date(), duration, task)
        except Exception as error:
            raise OperationFailedError("Task work was saved but statistics failed", effects_state="partial") from error
        return OperationResult("record-work", target, value=task, affected_ids=(target.id or "",))

    def _snooze_task(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        unknown = set(parameters) - {"duration", "now"}
        if unknown:
            raise ValidationError("Unknown snooze-task parameter", details={"field": sorted(unknown)[0]})
        duration = self._as_time_amount(parameters.get("duration", "5m"), "duration")
        now = parameters.get("now", TimePoint.now())
        if not isinstance(now, TimePoint):
            raise ValidationError("now must be a TimePoint", details={"field": "now"})
        task = copy.deepcopy(self.read_task(target.id or ""))
        task.setStart(now + duration)
        return self._save_sequential("snooze-task", target, [task], value=task)

    def _raise_event(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        if target.kind != "event" or not target.id:
            raise ValidationError("raise-event requires an event name", details={"field": "target"})
        if parameters:
            raise ValidationError("raise-event accepts no parameters", details={"field": "parameters"})
        now = TimePoint.now()
        tasks = [
            copy.deepcopy(task)
            for task in self._all_tasks()
            if task.getEventWaited() == target.id
        ]
        for task in tasks:
            task.setEventWaited(None)
            task.setStart(now)
        return self._save_sequential("raise-event", target, tasks, value=len(tasks))

    def _save_sequential(
        self,
        operation_type: str,
        target: OperationTarget,
        tasks: list[ITaskModel],
        *,
        value: Any,
    ) -> OperationResult:
        saved_ids: list[str] = []
        for task in tasks:
            try:
                self._task_provider.saveTask(task)
            except Exception as error:
                effects = "partial" if saved_ids else "unknown"
                raise OperationFailedError(
                    "The operation could not save every affected task",
                    effects_state=effects,
                    details={"saved_count": str(len(saved_ids))},
                ) from error
            saved_ids.append(task.getTaskUID())
        return OperationResult(operation_type, target, value=value, affected_ids=tuple(saved_ids))

    def _discard_pending_task_reservations(self) -> None:
        self._task_provider.discardPendingTaskReservations()

    def _prepare_changes(self, task: ITaskModel, changes: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, Mapping):
            raise ValidationError("changes must be an object", details={"field": "changes"})
        unknown = set(changes) - self._EDIT_FIELDS
        if unknown:
            raise ValidationError("Unknown or read-only task field", details={"field": sorted(unknown)[0]})
        prepared: dict[str, Any] = {}
        for field, value in changes.items():
            try:
                if field == "description":
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError("description must be a non-empty string")
                    prepared[field] = value
                elif field == "context":
                    self._validate_context(value)
                    prepared[field] = value
                elif field in ("start", "due"):
                    if not isinstance(value, (str, TimePoint)):
                        raise ValueError(f"{field} must be a time expression")
                    prepared[field] = value if isinstance(value, TimePoint) else self._parse_time(task, field, value)
                elif field == "severity":
                    if isinstance(value, bool):
                        raise ValueError("severity must be numeric")
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError("severity must be finite")
                    prepared[field] = number
                elif field == "total_cost":
                    prepared[field] = self._as_time_amount(value, field)
                elif field == "calm":
                    if not isinstance(value, bool):
                        raise ValueError("calm must be a boolean")
                    prepared[field] = value
                elif field in ("raised", "waited"):
                    if value is not None and not isinstance(value, str):
                        raise ValueError(f"{field} must be a string or null")
                    prepared[field] = value
            except DomainError:
                raise
            except Exception as error:
                raise ValidationError(str(error), details={"field": field}) from error
        return prepared

    def _edit_task_with_effort_delta(
        self,
        task_id: str,
        changes: Mapping[str, Any],
        delta: Any,
    ) -> ITaskModel:
        original = self.read_task(task_id)
        prepared = self._prepare_changes(original, changes)
        amount = self._as_time_amount(delta, "effort_delta")
        candidate = copy.deepcopy(original)
        self._apply_changes(candidate, prepared)
        candidate.setInvestedEffort(candidate.getInvestedEffort() + amount)
        candidate.setTotalCost(candidate.getTotalCost() - amount)
        try:
            self._task_provider.saveTask(candidate)
        except Exception as error:
            raise OperationFailedError("The task could not be saved", effects_state="unknown") from error
        return candidate

    @staticmethod
    def _apply_changes(task: ITaskModel, changes: Mapping[str, Any]) -> None:
        for field, value in changes.items():
            if field == "description":
                task.setDescription(value)
            elif field == "context":
                task.setContext(value)
            elif field == "start":
                task.setStart(value)
            elif field == "due":
                task.setDue(value)
            elif field == "severity":
                task.setSeverity(value)
            elif field == "total_cost":
                task.setTotalCost(value)
            elif field == "calm":
                task.setCalm(value)
            elif field == "raised":
                task.setEventRaised(value)
            elif field == "waited":
                task.setEventWaited(value)

    def _validate_context(self, context: Any) -> None:
        if not isinstance(context, str) or not any(
            context.startswith(category["prefix"]) for category in self._categories
        ):
            raise ValidationError("Context does not match a configured category", details={"field": "context"})

    @staticmethod
    def _as_time_amount(value: Any, field: str) -> TimeAmount:
        if isinstance(value, TimeAmount):
            amount = value
        elif isinstance(value, str):
            try:
                amount = TimeAmount(value)
            except Exception as error:
                raise ValidationError("Invalid duration", details={"field": field}) from error
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                if not math.isfinite(float(value)):
                    raise ValueError("duration must be finite")
                amount = TimeAmount(f"{value}p")
            except Exception as error:
                raise ValidationError("Invalid duration", details={"field": field}) from error
        else:
            raise ValidationError("Expected a duration", details={"field": field})
        try:
            finite_amount = math.isfinite(amount.as_pomodoros())
        except Exception as error:
            raise ValidationError("Invalid duration", details={"field": field}) from error
        if not finite_amount:
            raise ValidationError("Duration must be finite", details={"field": field})
        return amount

    @staticmethod
    def _parse_time(task: ITaskModel, field: str, value: str) -> TimePoint:
        try:
            if field == "start":
                is_relative = value.startswith(("+", "-", "now", "today", "tomorrow"))
                if not is_relative:
                    is_relative = value.count(":") == 1 and "T" not in value
                if not is_relative:
                    return TimePoint(datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M"))
            else:
                is_relative = value.startswith(("+", "-", "today", "tomorrow")) or value.count(":") == 1
                if not is_relative:
                    return TimePoint(datetime.datetime.strptime(value, "%Y-%m-%d"))

            current = task.getStart() if field == "start" else task.getDue()
            for part in value.split(";"):
                if part == "now":
                    current = TimePoint.now()
                elif part == "today":
                    current = TimePoint.today()
                elif part == "tomorrow":
                    current = TimePoint.tomorrow()
                elif ":" in part and "T" not in part:
                    current = current.strip_time() + TimeAmount(part)
                elif part.startswith(("+", "-")):
                    current = current + TimeAmount(part)
                else:
                    raise ValueError("Unsupported relative time component")
            return current
        except Exception as error:
            raise ValidationError("Invalid time expression", details={"field": field}) from error

    def _validate_view(self, view: TaskView) -> None:
        if not isinstance(view, TaskView):
            raise ValidationError("view must be a TaskView", details={"field": "view"})
        if type(view.page) is not int or view.page < 1:
            raise ValidationError("page must be a positive integer", details={"field": "page"})
        if type(view.page_size) is not int or view.page_size < 1:
            raise ValidationError("page_size must be a positive integer", details={"field": "page_size"})
        if not isinstance(view.filters, tuple) or not isinstance(view.search, tuple):
            raise ValidationError("filters and search must be tuples", details={"field": "view"})
        if any(not isinstance(item, str) or not item for item in view.filters):
            raise ValidationError("filters must contain names", details={"field": "filters"})
        if any(not isinstance(term, str) for term in view.search):
            raise ValidationError("search terms must be strings", details={"field": "search"})
        if not isinstance(view.algorithm, str) or not isinstance(view.heuristic, str):
            raise ValidationError("algorithm and heuristic must be names", details={"field": "view"})

    @staticmethod
    def _require_task_target(target: OperationTarget) -> None:
        if target.kind != "task" or not target.id:
            raise ValidationError("Operation requires a task identifier", details={"field": "target"})
