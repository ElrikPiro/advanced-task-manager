"""Reusable task reads and operations shared by communication adapters."""

import asyncio
import copy
import datetime
import json
import math
import os
import uuid
from collections.abc import Sequence
from typing import Any, Literal, Mapping, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.AtomicFileStore import AtomicWriteError
from src.Interfaces.ITaskModel import ITaskModel
from src.Interfaces.ITaskProvider import ITaskProvider
from src.MutationCoordinator import (
    MutationCoordinator,
    OperationIdConflict,
    OperationResultUnavailable,
)
from src.TelegramTaskListManager import TelegramTaskListManager
from src.Utils import AgendaContent, TaskInformation, TaskListContent, WorkloadStats
from src.wrappers.TimeManagement import TimeAmount, TimePoint
from src.taskproviders.TaskIdentityErrors import (
    AmbiguousTaskIdentityError,
    InvalidTaskIdentityError,
    MissingTaskIdentityError,
)

from .errors import (
    AmbiguousResourceError,
    DomainCalculationError,
    DomainError,
    InvalidResourceDataError,
    OperationConflictError,
    OperationFailedError,
    OperationResultUnavailableError,
    ResourceNotFoundError,
    ResourceReadError,
    UnsupportedOperationError,
    ValidationError,
)
from .models import (
    AgendaQuery,
    OperationIntent,
    OperationResult,
    OperationTarget,
    ProjectMutationResult,
    TaskView,
)


class TaskApplicationService:
    """Application boundary with explicit query inputs and typed outcomes.

    Reads resolve IDs without writing. A task's captured provider identity is
    carried through edits and operations until its first real save persists it.
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
    _PROVIDER_FIELDS_BY_EDIT_FIELD = {
        "description": "description",
        "context": "context",
        "start": "start",
        "due": "due",
        "severity": "severity",
        "total_cost": "totalCost",
        "calm": "calm",
        "raised": "raised",
        "waited": "waited",
    }

    def __init__(
        self,
        task_provider: ITaskProvider,
        scheduling: Any,
        statistics_service: Any,
        task_list_manager: TelegramTaskListManager,
        categories: list[dict[str, str]],
        project_manager: Any | None = None,
        mutation_coordinator: Any | None = None,
    ) -> None:
        self._task_provider = task_provider
        self._scheduling = scheduling
        self._statistics_service = statistics_service
        self._task_list_manager = task_list_manager
        self._categories = categories
        self._project_manager = project_manager
        self._mutation_coordinator = self._resolve_mutation_coordinator(
            mutation_coordinator,
            task_provider,
            project_manager,
            statistics_service,
        )

    @staticmethod
    def _resolve_mutation_coordinator(
        explicit: Any | None,
        task_provider: Any,
        project_manager: Any | None,
        statistics_service: Any | None,
    ) -> Any | None:
        """Reuse one FIFO across the provider, its broker and project writes."""
        file_broker = getattr(task_provider, "fileBroker", None)
        json_providers = [
            getattr(task_provider, "taskJsonProvider", None),
            getattr(task_provider, "TaskJsonProvider", None),
        ]
        sources = [
            task_provider,
            file_broker,
            getattr(task_provider, "file_broker", None),
            *json_providers,
            project_manager,
            statistics_service,
            getattr(statistics_service, "fileBroker", None),
        ]
        found: list[Any] = []
        for source in sources:
            coordinator = getattr(source, "mutation_coordinator", None)
            if isinstance(coordinator, MutationCoordinator):
                if all(coordinator is not existing for existing in found):
                    found.append(coordinator)
        if explicit is not None:
            if not callable(getattr(explicit, "run_operation", None)) or not callable(
                getattr(explicit, "run_or_inline", None)
            ):
                raise TypeError("mutation_coordinator must provide run_operation and run_or_inline")
            if any(explicit is not existing for existing in found):
                raise ValueError("Task providers and project managers must share one mutation coordinator")
            selected = explicit
        elif len(found) > 1:
            raise ValueError("Task providers and project managers must share one mutation coordinator")
        elif found:
            selected = found[0]
        elif isinstance(task_provider, ITaskProvider):
            selected = MutationCoordinator()
        else:
            return None

        for source in sources:
            existing = getattr(source, "mutation_coordinator", None) if source is not None else None
            if source is not None and existing is not selected and not isinstance(
                existing, MutationCoordinator
            ):
                try:
                    setattr(source, "mutation_coordinator", selected)
                except (AttributeError, TypeError):
                    pass
        return selected

    def _all_tasks(self, *, include_completed: bool = True) -> list[ITaskModel]:
        """Load current provider data without running discovery or maintenance."""
        try:
            return list(self._task_provider.getTaskList(include_completed=include_completed))
        except InvalidTaskIdentityError as error:
            raise InvalidResourceDataError("Task data declares an invalid identifier") from error
        except AmbiguousTaskIdentityError as error:
            raise AmbiguousResourceError("More than one task matches the requested identifier") from error
        except MissingTaskIdentityError as error:
            raise ResourceNotFoundError("No task matches the requested identifier") from error
        except DomainError:
            raise
        except Exception as error:
            raise ResourceReadError("Task data could not be read") from error

    def discover_initialize(self) -> list[ITaskModel]:
        """Run provider discovery explicitly before a communication listener."""
        coordinator = self._mutation_coordinator
        run_or_inline = getattr(coordinator, "run_or_inline", None)
        if callable(run_or_inline):
            return cast(list[ITaskModel], run_or_inline(self._discover_initialize))
        return self._discover_initialize()

    def _discover_initialize(self) -> list[ITaskModel]:
        discover = getattr(self._task_provider, "discoverTasks", None)
        if not callable(discover):
            return self._all_tasks(include_completed=False)
        try:
            return list(discover())
        except InvalidTaskIdentityError as error:
            raise InvalidResourceDataError("Task data declares an invalid identifier") from error
        except AmbiguousTaskIdentityError as error:
            raise AmbiguousResourceError("More than one task matches the requested identifier") from error
        except MissingTaskIdentityError as error:
            raise ResourceNotFoundError("No task matches the requested identifier") from error
        except DomainError:
            raise
        except Exception as error:
            raise ResourceReadError("Task discovery failed") from error

    def maintain(self) -> list[ITaskModel]:
        """Expose an explicit maintenance hook for the existing provider cycle."""
        return self.discover_initialize()

    def read_task(
        self,
        task_id: str,
        *,
        task_models: Sequence[ITaskModel] | None = None,
    ) -> ITaskModel:
        """Read one task by its currently exposed UID, including completed tasks."""
        if not isinstance(task_id, str) or not task_id:
            raise ValidationError("A task identifier is required", details={"field": "id"})
        source_tasks = self._all_tasks() if task_models is None else list(task_models)
        matches = [task for task in source_tasks if self._capture_task_id(task) == task_id]
        if not matches:
            raise ResourceNotFoundError("No task matches the requested identifier")
        if len(matches) > 1:
            raise AmbiguousResourceError("More than one task matches the requested identifier")
        return matches[0]

    def read_task_models(self, *, include_completed: bool = True) -> list[ITaskModel]:
        """Return a fresh, read-only model snapshot for resource projection."""
        return self._all_tasks(include_completed=include_completed)

    def query_tasks(
        self,
        view: TaskView,
        *,
        task_models: Sequence[ITaskModel] | None = None,
    ) -> TaskListContent:
        """Run a task query with its filters, strategies and page supplied inline."""
        self._validate_view(view)
        tasks = (
            self._all_tasks(include_completed=False)
            if task_models is None
            else [task for task in task_models if task.getStatus() != "x"]
        )
        try:
            manager = self._task_list_manager.clone_for_view(tasks, view)
        except DomainError:
            raise
        except ValueError as error:
            self._raise_task_identity_error(error)
            raise ValidationError(str(error), details={"field": "view"}) from error
        try:
            return manager.get_task_list_content()
        except DomainError:
            raise
        except Exception as error:
            self._raise_task_identity_error(error)
            raise DomainCalculationError("Task view could not be calculated") from error

    def read_agenda(
        self,
        query: AgendaQuery,
        *,
        task_models: Sequence[ITaskModel] | None = None,
    ) -> AgendaContent:
        """Calculate an agenda from current tasks and explicit date/heuristic."""
        if not isinstance(query.day, TimePoint):
            raise ValidationError("Agenda day must be a TimePoint", details={"field": "day"})
        tasks = self._all_tasks(include_completed=True) if task_models is None else list(task_models)
        try:
            manager = self._task_list_manager.clone_for_view(
                tasks,
                TaskView(heuristic=query.heuristic),
            )
        except DomainError:
            raise
        except ValueError as error:
            self._raise_task_identity_error(error)
            raise ValidationError(str(error), details={"field": "heuristic"}) from error
        try:
            return manager.get_day_agenda_content(query.day, self._categories)
        except DomainError:
            raise
        except Exception as error:
            self._raise_task_identity_error(error)
            raise DomainCalculationError("Agenda could not be calculated") from error

    def read_task_information(self, task_id: str, *, extended: bool = False) -> TaskInformation:
        """Return typed detail data for a task, independent of list selection."""
        task = self.read_task(task_id)
        try:
            return self._task_list_manager.get_task_information(
                task,
                self._task_provider,
                extended,
            )
        except DomainError:
            raise
        except Exception as error:
            self._raise_task_identity_error(error)
            raise ResourceReadError("Task detail could not be read") from error

    def read_task_information_for(
        self,
        task: ITaskModel,
        *,
        extended: bool = False,
        task_models: Sequence[ITaskModel] | None = None,
    ) -> TaskInformation:
        """Project typed detail data for an already-resolved model snapshot."""
        try:
            clone_for_view = getattr(self._task_list_manager, "clone_for_view", None)
            if callable(clone_for_view):
                manager = clone_for_view(
                    self._all_tasks(include_completed=True)
                    if task_models is None
                    else list(task_models),
                    TaskView(filters=(), algorithm="", heuristic=""),
                )
            else:
                manager = self._task_list_manager
            return cast(
                TaskInformation,
                manager.get_task_information(task, self._task_provider, extended),
            )
        except DomainError:
            raise
        except Exception as error:
            self._raise_task_identity_error(error)
            raise ResourceReadError("Task detail could not be read") from error

    def read_statistics(
        self,
        view: TaskView,
        *,
        task_models: Sequence[ITaskModel] | None = None,
    ) -> WorkloadStats:
        """Calculate live work statistics for an explicit, unpaged task view."""
        self._validate_view(view)
        try:
            tasks = (
                self._all_tasks(include_completed=False)
                if task_models is None
                else [task for task in task_models if task.getStatus() != "x"]
            )
            manager = self._task_list_manager.clone_for_view(tasks, view)
            read_stats = getattr(self._statistics_service, "readWorkloadStats", None)
            if callable(read_stats):
                return cast(WorkloadStats, read_stats(manager.filtered_task_list))
            get_stats = getattr(self._statistics_service, "getWorkloadStats", None)
            if not callable(get_stats):
                raise ResourceReadError("Statistics are unavailable")
            return cast(WorkloadStats, get_stats(manager.filtered_task_list))
        except DomainError:
            raise
        except ValueError as error:
            self._raise_task_identity_error(error)
            raise ValidationError(str(error), details={"field": "view"}) from error
        except Exception as error:
            self._raise_task_identity_error(error)
            raise DomainCalculationError("Statistics could not be calculated") from error

    def read_events(self) -> Any:
        """Read event counts across open and completed tasks without changing them."""
        try:
            read_events = getattr(self._statistics_service, "getEventStatistics", None)
            if not callable(read_events):
                raise ResourceReadError("Event statistics are unavailable")
            return read_events(self._all_tasks(include_completed=True))
        except DomainError:
            raise
        except Exception as error:
            self._raise_task_identity_error(error)
            raise DomainCalculationError("Event statistics could not be calculated") from error

    def read_strategies(self) -> dict[str, Any]:
        """Read strategy descriptions without changing the selected channel view."""
        try:
            filters = self._task_list_manager.get_filter_list().get("filterList", [])
            return {
                "filters": list(filters),
                "algorithms": list(self._task_list_manager.get_algorithm_list()),
                "heuristics": list(self._task_list_manager.get_heuristic_list()),
            }
        except Exception as error:
            raise ResourceReadError("Strategy catalog could not be read") from error

    def read_projects(self, status: str = "open") -> list[dict[str, Any]]:
        """Read projects by status through the configured storage manager."""
        manager = self._project_manager
        reader = getattr(manager, "read_projects", None)
        if not callable(reader):
            raise UnsupportedOperationError("Projects are unavailable for this storage mode")
        try:
            return cast(list[dict[str, Any]], reader(status))
        except DomainError:
            raise
        except Exception as error:
            raise ResourceReadError("Project data could not be read") from error

    def read_project(self, name: str) -> dict[str, Any]:
        """Read one project without exposing provider paths or command text."""
        manager = self._project_manager
        reader = getattr(manager, "read_project", None)
        if not callable(reader):
            raise UnsupportedOperationError("Projects are unavailable for this storage mode")
        try:
            return cast(dict[str, Any], reader(name))
        except DomainError:
            raise
        except Exception as error:
            raise ResourceReadError("Project data could not be read") from error

    def project_operation_capabilities(self) -> dict[str, dict[str, Any]]:
        """Return only the project operations and fields supported by storage."""
        manager = self._project_manager
        capabilities = getattr(manager, "get_operation_capabilities", None)
        if not callable(capabilities):
            return {}
        try:
            return cast(dict[str, dict[str, Any]], capabilities())
        except Exception as error:
            raise ResourceReadError("Project capabilities could not be read") from error

    def task_context_prefixes(self) -> tuple[str, ...]:
        """Return the accepted context prefixes without changing application state."""
        return tuple(
            category["prefix"]
            for category in self._categories
            if isinstance(category, dict) and isinstance(category.get("prefix"), str)
        )

    def edit_task(self, task_id: str, changes: Mapping[str, Any]) -> ITaskModel:
        """Retain the original edit entry point while admitting it through the FIFO."""
        result = self.submit_operation(
            uuid.uuid4(),
            "edit-task",
            OperationTarget("task", task_id),
            {"changes": changes},
        )
        return cast(ITaskModel, result.value)

    def patch_task(self, task_id: str, changes: Mapping[str, Any]) -> ITaskModel:
        """Apply one validated set of replacement fields as a single queued edit."""
        return self.edit_task(task_id, changes)

    def execute_operation(
        self,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationResult:
        """Execute one synchronous operation using a generated operation identity."""
        return self.submit_operation(uuid.uuid4(), operation_type, target, parameters)

    async def execute_operation_async(
        self,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
        *,
        operation_id: str | uuid.UUID | None = None,
    ) -> OperationResult:
        """Execute an internal operation without blocking an asynchronous caller."""
        return await self.submit_operation_async(
            operation_id or uuid.uuid4(), operation_type, target, parameters
        )

    def submit_operation(
        self,
        operation_id: str | uuid.UUID,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationResult:
        """Admit a client-identified operation, or return its known outcome."""
        self.validate_operation_structure(operation_type, target, parameters)
        normalized_id = self._normalize_operation_id(operation_id)
        intent = self._make_operation_intent(operation_type, target, parameters)
        coordinator = self._mutation_coordinator
        if coordinator is None:
            return self._execute_operation_intent(intent)
        try:
            return cast(
                OperationResult,
                coordinator.run_operation(
                    normalized_id,
                    intent,
                    self._execute_operation_intent,
                ),
            )
        except OperationIdConflict as error:
            raise OperationConflictError(normalized_id) from error

    async def submit_operation_async(
        self,
        operation_id: str | uuid.UUID,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationResult:
        """Admit an operation before yielding, without blocking the event loop."""
        self.validate_operation_structure(operation_type, target, parameters)
        normalized_id = self._normalize_operation_id(operation_id)
        intent = self._make_operation_intent(operation_type, target, parameters)
        coordinator = self._mutation_coordinator
        if coordinator is None:
            return await asyncio.to_thread(self._execute_operation_intent, intent)
        run_async = getattr(coordinator, "run_operation_async", None)
        if not callable(run_async):
            try:
                return cast(
                    OperationResult,
                    await asyncio.to_thread(
                        coordinator.run_operation,
                        normalized_id,
                        intent,
                        self._execute_operation_intent,
                    ),
                )
            except OperationIdConflict as error:
                raise OperationConflictError(normalized_id) from error
        try:
            return cast(
                OperationResult,
                await run_async(normalized_id, intent, self._execute_operation_intent),
            )
        except OperationIdConflict as error:
            raise OperationConflictError(normalized_id) from error

    def get_receipt(self, operation_id: str | uuid.UUID) -> Any:
        """Return a detached receipt without starting or repeating its operation."""
        normalized_id = self._normalize_operation_id(operation_id)
        coordinator = self._mutation_coordinator
        if coordinator is None:
            raise OperationResultUnavailableError(normalized_id)
        try:
            return coordinator.get_receipt(normalized_id)
        except OperationResultUnavailable as error:
            raise OperationResultUnavailableError(normalized_id) from error

    def get_operation_receipt(self, operation_id: str | uuid.UUID) -> Any:
        """Alias that names the receipt resource explicitly."""
        return self.get_receipt(operation_id)

    @staticmethod
    def _normalize_operation_id(operation_id: str | uuid.UUID) -> str:
        try:
            return str(uuid.UUID(str(operation_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError(
                "operation_id must be a UUID",
                details={"field": "operation_id"},
                effects_state="none",
            ) from error

    @staticmethod
    def _make_operation_intent(
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationIntent:
        try:
            return OperationIntent(
                operation_type=operation_type,
                target=copy.deepcopy(target),
                parameters=copy.deepcopy(dict(parameters)),
            )
        except Exception as error:
            raise ValidationError(
                "Operation parameters cannot be copied safely",
                details={"field": "parameters"},
                effects_state="none",
            ) from error

    def validate_operation_structure(
        self,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> None:
        """Reject malformed operation structure without reading provider state."""
        if not isinstance(target, OperationTarget):
            raise ValidationError(
                "Operation target must be typed",
                details={"field": "target"},
                effects_state="none",
            )
        if not isinstance(parameters, Mapping):
            raise ValidationError(
                "Operation parameters must be an object",
                details={"field": "parameters"},
                effects_state="none",
            )
        if not isinstance(operation_type, str) or not operation_type:
            raise ValidationError(
                "Operation type is required",
                details={"field": "operation_type"},
                effects_state="none",
            )

        if operation_type == "create-task":
            self._validate_create_structure(target, parameters)
        elif operation_type == "edit-task":
            self._validate_edit_structure(target, parameters)
        elif operation_type == "complete-task":
            self._validate_task_target_structure(target)
            self._require_no_parameters(operation_type, parameters)
        elif operation_type == "schedule-task":
            self._validate_task_target_structure(target)
            unknown = set(parameters) - {"effort_per_day"}
            self._reject_unknown_parameter(unknown)
            effort = parameters.get("effort_per_day", "")
            if not isinstance(effort, str):
                self._invalid_field("effort_per_day", "effort_per_day must be a string")
        elif operation_type == "record-work":
            self._validate_task_target_structure(target)
            unknown = set(parameters) - {"duration", "now"}
            self._reject_unknown_parameter(unknown)
            if "duration" not in parameters:
                self._invalid_field("duration", "duration is required")
            self._as_time_amount(parameters["duration"], "duration")
            self._validate_optional_now(parameters)
        elif operation_type == "snooze-task":
            self._validate_task_target_structure(target)
            unknown = set(parameters) - {"duration", "now"}
            self._reject_unknown_parameter(unknown)
            if "duration" in parameters:
                self._as_time_amount(parameters["duration"], "duration")
            self._validate_optional_now(parameters)
        elif operation_type == "raise-event":
            if target.kind != "event" or not isinstance(target.id, str) or not target.id.strip():
                self._invalid_field("target", "raise-event requires an event name")
            self._require_no_parameters(operation_type, parameters)
        elif operation_type in {"open-project", "close-project", "hold-project", "edit-project-content"}:
            if not callable(getattr(self._project_manager, "perform_operation", None)):
                raise UnsupportedOperationError(
                    "Project operations are unavailable for this storage mode",
                    effects_state="none",
                )
            self._validate_project_operation_structure(operation_type, target, parameters)
        else:
            raise UnsupportedOperationError(
                f"Unsupported operation type: {operation_type}", effects_state="none"
            )

    def _execute_operation_intent(self, admitted: object) -> OperationResult:
        if not isinstance(admitted, OperationIntent):
            raise ValidationError("Admitted operation intent is invalid", effects_state="none")
        operation_type = admitted.operation_type
        target = admitted.target
        parameters = admitted.parameters
        if operation_type == "create-task":
            return self._create_task(target, parameters)
        if operation_type == "edit-task":
            changes = parameters.get("changes", {})
            delta = parameters.get("effort_delta")
            if delta is not None:
                updated = self._edit_task_with_effort_delta(target.id or "", changes, delta)
            else:
                updated = self._edit_task_in_turn(target.id or "", changes)
            return OperationResult(operation_type, target, value=updated, affected_ids=(target.id or "",))
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
        return self._execute_project_operation(operation_type, target, parameters)

    def _edit_task_in_turn(self, task_id: str, changes: Mapping[str, Any]) -> ITaskModel:
        task = self.read_task(task_id)
        resolved_id = self._capture_task_id(task)
        prepared = self._prepare_changes(task, changes)
        candidate = copy.deepcopy(task)
        try:
            self._apply_changes(candidate, prepared)
            self._mark_requested_task_fields(candidate, prepared)
            self._assert_task_identity(candidate, resolved_id)
            self._save_task(candidate, expected_id=resolved_id)
        except DomainError:
            raise
        except Exception as error:
            raise OperationFailedError(
                "The task could not be saved",
                effects_state="unknown",
                details={"resource": "task"},
            ) from error
        return candidate

    @staticmethod
    def _invalid_field(field: str, message: str) -> None:
        raise ValidationError(message, details={"field": field}, effects_state="none")

    @classmethod
    def _reject_unknown_parameter(cls, unknown: set[str]) -> None:
        if unknown:
            cls._invalid_field(str(sorted(unknown, key=str)[0]), "Unknown operation parameter")

    @classmethod
    def _require_no_parameters(cls, operation_type: str, parameters: Mapping[str, Any]) -> None:
        if parameters:
            cls._invalid_field("parameters", f"{operation_type} accepts no parameters")

    @classmethod
    def _validate_task_target_structure(cls, target: OperationTarget) -> None:
        if target.kind != "task" or not isinstance(target.id, str) or not target.id:
            cls._invalid_field("target", "Operation requires a task identifier")

    def _validate_create_structure(
        self,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> None:
        if target.kind not in ("tasks", "task") or target.id is not None:
            self._invalid_field("target", "create-task targets the task collection")
        description = parameters.get("description")
        if not isinstance(description, str) or not description.strip():
            self._invalid_field("description", "description is required")
        unknown = set(parameters) - {"description", "context", "total_cost"}
        self._reject_unknown_parameter(unknown)
        if ("context" in parameters) != ("total_cost" in parameters):
            self._invalid_field("context", "context and total_cost must be supplied together")
        context = parameters.get("context", "inbox")
        self._validate_context(context)
        self._as_time_amount(parameters.get("total_cost", "1p"), "total_cost")

    def _validate_edit_structure(
        self,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> None:
        self._validate_task_target_structure(target)
        unknown = set(parameters) - {"changes", "effort_delta"}
        self._reject_unknown_parameter(unknown)
        changes = parameters.get("changes", {})
        if not isinstance(changes, Mapping):
            self._invalid_field("changes", "changes must be an object")
        unknown_fields = set(changes) - self._EDIT_FIELDS
        self._reject_unknown_parameter(unknown_fields)
        for field, value in changes.items():
            if field == "description" and (not isinstance(value, str) or not value.strip()):
                self._invalid_field(field, "description must be a non-empty string")
            elif field == "context":
                self._validate_context(value)
            elif field in ("start", "due") and not isinstance(value, (str, TimePoint)):
                self._invalid_field(field, f"{field} must be a time expression")
            elif field == "severity":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    self._invalid_field(field, "severity must be finite numeric data")
            elif field == "total_cost":
                self._as_time_amount(value, field)
            elif field == "calm" and not isinstance(value, bool):
                self._invalid_field(field, "calm must be a boolean")
            elif field in ("raised", "waited") and value is not None and not isinstance(value, str):
                self._invalid_field(field, f"{field} must be a string or null")
        if "effort_delta" in parameters and parameters["effort_delta"] is not None:
            self._as_time_amount(parameters["effort_delta"], "effort_delta")

    @staticmethod
    def _validate_optional_now(parameters: Mapping[str, Any]) -> None:
        now = parameters.get("now")
        if now is not None and not isinstance(now, TimePoint):
            raise ValidationError(
                "now must be a TimePoint",
                details={"field": "now"},
                effects_state="none",
            )

    def _validate_project_operation_structure(
        self,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> None:
        if target.kind != "project" or not isinstance(target.id, str) or not target.id.strip():
            self._invalid_field("target", f"{operation_type} requires a project name")
        if operation_type in {"close-project", "hold-project"}:
            self._require_no_parameters(operation_type, parameters)
        elif operation_type == "open-project":
            unknown = set(parameters) - {"description"}
            self._reject_unknown_parameter(unknown)
            description = parameters.get("description", "")
            if not isinstance(description, str):
                self._invalid_field("description", "description must be a string")
        else:
            unknown = set(parameters) - {"action", "line", "position", "content", "description"}
            self._reject_unknown_parameter(unknown)
            if "description" in parameters:
                if set(parameters) != {"description"} or not isinstance(parameters["description"], str):
                    self._invalid_field("description", "description must be the only content parameter")
            else:
                action = parameters.get("action")
                if not isinstance(action, str) or action not in {"replace", "insert", "delete"}:
                    self._invalid_field("action", "action must be replace, insert, or delete")
                if "line" in parameters and "position" in parameters:
                    self._invalid_field("line", "supply line or position, not both")
                line = parameters.get("line", parameters.get("position"))
                if type(line) is not int or line < 1:
                    self._invalid_field("line", "line or position must be a positive integer")
                if action in {"replace", "insert"}:
                    if not isinstance(parameters.get("content"), str):
                        self._invalid_field("content", "content is required")
                elif "content" in parameters:
                    self._invalid_field("content", "delete does not accept content")
        manager_validator = getattr(self._project_manager, "validate_operation_structure", None)
        if callable(manager_validator):
            manager_validator(operation_type, target.id or "", parameters)

    def _execute_project_operation(
        self,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationResult:
        manager = self._project_manager
        apply_operation = getattr(manager, "perform_operation", None)
        if not callable(apply_operation):
            raise UnsupportedOperationError(
                "Project operations are unavailable for this storage mode", effects_state="none"
            )
        try:
            value = apply_operation(operation_type, target.id or "", parameters)
        except DomainError:
            raise
        except Exception as error:
            state = getattr(error, "effects_state", None)
            effects: Literal["none", "partial", "unknown"] = (
                state if state in {"none", "partial", "unknown"} else "unknown"
            )
            raise OperationFailedError(
                "The project could not be saved",
                effects_state=effects,
                details={"resource": "project"},
            ) from error
        if not isinstance(value, ProjectMutationResult):
            raise OperationFailedError(
                "The project manager returned no typed result",
                effects_state="unknown",
                details={"resource": "project"},
            )
        return OperationResult(
            operation_type,
            target,
            value=value,
            affected_ids=(value.name,),
        )

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
            task_id = self._capture_task_id(task)
            task.setContext(context)
            task.setTotalCost(cost_amount)
            self._assert_task_identity(task, task_id)
            self._save_task(task, expected_id=task_id)
        except DomainError:
            self._discard_pending_task_reservations()
            raise
        except Exception as error:
            self._discard_pending_task_reservations()
            self._raise_task_identity_error(error)
            raise OperationFailedError("The new task could not be saved", effects_state="unknown") from error
        return OperationResult("create-task", target, value=task, affected_ids=(task_id,))

    def _complete_task(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        if parameters:
            raise ValidationError("complete-task accepts no parameters", details={"field": "parameters"})
        original = self.read_task(target.id or "")
        original_id = self._capture_task_id(original)
        task = copy.deepcopy(original)
        related: list[ITaskModel] = []
        related_ids: list[str] = []
        event = task.getEventRaised()
        if isinstance(event, str):
            now = TimePoint.now()
            # The target task may itself await the event it is now raising.
            # It is saved as the completed target below, so update it here and
            # avoid a duplicate save for the same task identity.
            if task.getEventWaited() == event:
                task.setEventWaited(None)
                task.setStart(now)
            for candidate in self._all_tasks():
                candidate_id = self._capture_task_id(candidate)
                matches_target = candidate_id != original_id
                awaits_event = candidate.getEventWaited() == event
                if matches_target and awaits_event:
                    related.append(copy.deepcopy(candidate))
                    related_ids.append(candidate_id)
            for candidate in related:
                candidate.setEventWaited(None)
                candidate.setStart(now)
        task.setStatus("x")
        self._assert_task_identity(task, original_id)
        expected_ids = [*related_ids, original_id]
        for candidate, expected_id in zip(related, related_ids):
            self._assert_task_identity(candidate, expected_id)
        return self._save_sequential(
            "complete-task", target, [*related, task], value=task, expected_ids=expected_ids
        )

    def _schedule_task(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        unknown = set(parameters) - {"effort_per_day"}
        if unknown:
            raise ValidationError("Unknown schedule-task parameter", details={"field": sorted(unknown)[0]})
        effort = parameters.get("effort_per_day", "")
        if not isinstance(effort, str):
            raise ValidationError("effort_per_day must be a string", details={"field": "effort_per_day"})
        original = self.read_task(target.id or "")
        original_id = self._capture_task_id(original)
        task_copy = copy.deepcopy(original)
        try:
            tasks = list(self._scheduling.schedule(task_copy, effort))
        except DomainError:
            self._discard_pending_task_reservations()
            raise
        except Exception as error:
            self._discard_pending_task_reservations()
            self._raise_task_identity_error(error)
            raise OperationFailedError("The task could not be scheduled", effects_state="none") from error
        if not tasks:
            self._discard_pending_task_reservations()
            raise OperationFailedError("Scheduling produced no tasks", effects_state="none")
        try:
            all_existing_ids = {self._capture_task_id(task) for task in self._all_tasks()}
            scheduled_ids = [self._capture_task_id(task) for task in tasks]
        except DomainError:
            self._discard_pending_task_reservations()
            raise
        if scheduled_ids[0] != original_id:
            self._discard_pending_task_reservations()
            raise InvalidResourceDataError("Scheduling changed the identity of the original task")
        new_ids = scheduled_ids[1:]
        if len(set(scheduled_ids)) != len(scheduled_ids) or any(
            not task_id or task_id in all_existing_ids for task_id in new_ids
        ):
            self._discard_pending_task_reservations()
            raise AmbiguousResourceError("Scheduled tasks do not have distinct identifiers")
        return self._save_sequential(
            "schedule-task", target, tasks, value=tasks, expected_ids=scheduled_ids
        )

    def _record_work(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        self._require_task_target(target)
        unknown = set(parameters) - {"duration", "now"}
        if unknown:
            raise ValidationError("Unknown record-work parameter", details={"field": sorted(unknown)[0]})
        duration = self._as_time_amount(parameters.get("duration"), "duration")
        original = self.read_task(target.id or "")
        task_id = self._capture_task_id(original)
        task = copy.deepcopy(original)
        task.setInvestedEffort(task.getInvestedEffort() + duration)
        task.setTotalCost(task.getTotalCost() - duration)
        now = parameters.get("now", TimePoint.now())
        if not isinstance(now, TimePoint):
            raise ValidationError("now must be a TimePoint", details={"field": "now"})
        self._assert_task_identity(task, task_id)
        try:
            self._save_task(task, expected_id=task_id)
        except DomainError:
            raise
        except Exception as error:
            raise OperationFailedError(
                "The task could not be saved",
                effects_state="unknown",
                details={"resource": "task", "failed_id": task_id},
            ) from error
        try:
            self._statistics_service.doWork(now.datetime_representation.date(), duration, task)
        except Exception as error:
            write_state = getattr(error, "effects_state", None)
            details = self._persistence_error_details(error, "statistics")
            details["saved_count"] = "1"
            details["saved_ids"] = json.dumps([task_id], ensure_ascii=False)
            details["failed_resource"] = "statistics"
            operation_state: Literal["partial", "unknown"] = (
                "partial" if write_state == "none" else "unknown"
            )
            raise OperationFailedError(
                "Task work was saved but statistics could not be confirmed",
                effects_state=operation_state,
                details=details,
            ) from error
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
        original = self.read_task(target.id or "")
        task_id = self._capture_task_id(original)
        task = copy.deepcopy(original)
        task.setStart(now + duration)
        self._assert_task_identity(task, task_id)
        return self._save_sequential(
            "snooze-task", target, [task], value=task, expected_ids=[task_id]
        )

    def _raise_event(self, target: OperationTarget, parameters: Mapping[str, Any]) -> OperationResult:
        if target.kind != "event" or not target.id:
            raise ValidationError("raise-event requires an event name", details={"field": "target"})
        if parameters:
            raise ValidationError("raise-event accepts no parameters", details={"field": "parameters"})
        now = TimePoint.now()
        tasks: list[ITaskModel] = []
        task_ids: list[str] = []
        for original in self._all_tasks():
            if original.getEventWaited() != target.id:
                continue
            task_ids.append(self._capture_task_id(original))
            tasks.append(copy.deepcopy(original))
        for task, task_id in zip(tasks, task_ids):
            task.setEventWaited(None)
            task.setStart(now)
            self._assert_task_identity(task, task_id)
        return self._save_sequential(
            "raise-event", target, tasks, value=len(tasks), expected_ids=task_ids
        )

    def _save_sequential(
        self,
        operation_type: str,
        target: OperationTarget,
        tasks: list[ITaskModel],
        *,
        value: Any,
        expected_ids: list[str] | None = None,
    ) -> OperationResult:
        saved_ids: list[str] = []
        identities = expected_ids or [self._capture_task_id(task) for task in tasks]
        if len(identities) != len(tasks):
            raise InvalidResourceDataError("The number of task identities does not match the write set")
        if len(set(identities)) != len(identities):
            raise AmbiguousResourceError("More than one affected task has the same identifier")
        for task, expected_id in zip(tasks, identities):
            try:
                self._assert_task_identity(task, expected_id)
                self._save_task(task, expected_id=expected_id)
            except DomainError as error:
                self._attach_sequential_effects(error, saved_ids, expected_id)
                raise
            except Exception as error:
                error_details = self._persistence_error_details(error, "task")
                error_details["failed_id"] = expected_id
                state = getattr(error, "effects_state", None)
                effects: Literal["none", "partial", "unknown"] = (
                    "none" if state == "none" else "unknown"
                )
                if saved_ids and effects == "none":
                    effects = "partial"
                self._attach_saved_ids(error_details, saved_ids)
                if effects == "unknown":
                    error_details["uncertain_id"] = expected_id
                raise OperationFailedError(
                    "The operation could not save every affected task",
                    effects_state=effects,
                    details=error_details,
                ) from error
            saved_ids.append(expected_id)
        return OperationResult(operation_type, target, value=value, affected_ids=tuple(saved_ids))

    def _save_task(self, task: ITaskModel, *, expected_id: str) -> None:
        """Save using the identity resolved before mutation and preserve typed outcomes."""
        self._assert_task_identity(task, expected_id)
        try:
            self._task_provider.saveTask(task)
        except AtomicWriteError as error:
            details = self._persistence_error_details(error, "task")
            details["failed_id"] = expected_id
            if error.effects_state == "unknown":
                details["uncertain_id"] = expected_id
            raise OperationFailedError(
                "The task could not be saved",
                effects_state=error.effects_state,
                details=details,
            ) from error
        except InvalidTaskIdentityError as error:
            raise InvalidResourceDataError(
                "Task data declares an invalid identifier",
                effects_state=self._identity_write_effects_state(error),
                details=self._identity_write_details(error, expected_id),
            ) from error
        except AmbiguousTaskIdentityError as error:
            raise AmbiguousResourceError(
                "More than one task matches the requested identifier",
                effects_state=self._identity_write_effects_state(error),
                details=self._identity_write_details(error, expected_id),
            ) from error
        except MissingTaskIdentityError as error:
            raise ResourceNotFoundError(
                "The task no longer matches its resolved identifier",
                effects_state=self._identity_write_effects_state(error),
                details=self._identity_write_details(error, expected_id),
            ) from error
        except DomainError:
            raise
        except Exception as error:
            write_state = getattr(error, "effects_state", None)
            effects: Literal["none", "unknown"] = (
                "none" if write_state == "none" else "unknown"
            )
            details = self._persistence_error_details(error, "task")
            details["failed_id"] = expected_id
            if effects == "unknown":
                details["uncertain_id"] = expected_id
            raise OperationFailedError(
                "The task could not be saved",
                effects_state=effects,
                details=details,
            ) from error
        try:
            self._assert_task_identity(task, expected_id)
        except DomainError as error:
            raise OperationFailedError(
                "The task was saved but its identity could not be confirmed",
                effects_state="unknown",
                details={"resource": "task", "failed_id": expected_id, "uncertain_id": expected_id},
            ) from error

    @staticmethod
    def _persistence_error_details(error: Exception, resource: str) -> dict[str, str]:
        """Expose safe write-outcome metadata without leaking local file paths."""
        details = {"resource": resource}
        phase = getattr(error, "phase", None)
        if isinstance(phase, str):
            details["write_phase"] = phase
        if isinstance(error, AtomicWriteError):
            replaced = error.replaced
            details["write_replaced"] = (
                "true" if replaced is True else "false" if replaced is False else "unknown"
            )
        return details

    @staticmethod
    def _identity_write_effects_state(error: Exception) -> Literal["none", "unknown"]:
        """Treat identity failures as no-write unless a provider marks a post-commit uncertainty."""
        return "unknown" if getattr(error, "effects_state", None) == "unknown" else "none"

    @classmethod
    def _identity_write_details(cls, error: Exception, task_id: str) -> dict[str, str]:
        details = {"resource": "task", "failed_id": task_id}
        if cls._identity_write_effects_state(error) == "unknown":
            details["uncertain_id"] = task_id
        return details

    @staticmethod
    def _attach_saved_ids(details: dict[str, str], saved_ids: list[str]) -> None:
        details["saved_count"] = str(len(saved_ids))
        details["saved_ids"] = json.dumps(saved_ids, ensure_ascii=False)

    @classmethod
    def _attach_sequential_effects(
        cls,
        error: DomainError,
        saved_ids: list[str],
        failed_id: str,
    ) -> None:
        """Keep confirmed writes visible while preserving uncertain last-write outcomes."""
        cls._attach_saved_ids(error.details, saved_ids)
        error.details.setdefault("failed_id", failed_id)
        if error.effects_state == "unknown":
            error.details.setdefault("uncertain_id", failed_id)
        elif saved_ids:
            error.effects_state = "partial"
        elif error.effects_state is None:
            error.effects_state = "none"

    @staticmethod
    def _raise_task_identity_error(error: Exception) -> None:
        if isinstance(error, InvalidTaskIdentityError):
            raise InvalidResourceDataError("Task data declares an invalid identifier") from error
        if isinstance(error, AmbiguousTaskIdentityError):
            raise AmbiguousResourceError("More than one task matches the requested identifier") from error
        if isinstance(error, MissingTaskIdentityError):
            raise ResourceNotFoundError("No task matches the requested identifier") from error

    @classmethod
    def _capture_task_id(cls, task: ITaskModel) -> str:
        try:
            task_id = task.getTaskUID()
        except Exception as error:
            cls._raise_task_identity_error(error)
            raise
        if not isinstance(task_id, str) or not task_id:
            raise InvalidResourceDataError("Task data has an empty or invalid identifier")
        return task_id

    @classmethod
    def _assert_task_identity(cls, task: ITaskModel, expected_id: str) -> None:
        actual_id = cls._capture_task_id(task)
        if actual_id != expected_id:
            raise InvalidResourceDataError("A task's resolved identifier changed before it was saved")

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
        resolved_id = self._capture_task_id(original)
        prepared = self._prepare_changes(original, changes)
        amount = self._as_time_amount(delta, "effort_delta")
        candidate = copy.deepcopy(original)
        self._apply_changes(candidate, prepared)
        requested_provider_fields = self._mark_requested_task_fields(candidate, prepared)
        candidate.setInvestedEffort(candidate.getInvestedEffort() + amount)
        candidate.setTotalCost(candidate.getTotalCost() - amount)
        if amount.as_pomodoros() != 0:
            requested_provider_fields.update(("investedEffort", "totalCost"))
            setattr(candidate, "_task_provider_forced_fields", requested_provider_fields)
        self._assert_task_identity(candidate, resolved_id)
        try:
            self._save_task(candidate, expected_id=resolved_id)
        except DomainError:
            raise
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

    @classmethod
    def _mark_requested_task_fields(
        cls,
        task: ITaskModel,
        changes: Mapping[str, Any],
    ) -> set[str]:
        """Keep explicit edits authoritative even when equal to their read baseline."""
        requested = {
            cls._PROVIDER_FIELDS_BY_EDIT_FIELD[field]
            for field in changes
            if field in cls._PROVIDER_FIELDS_BY_EDIT_FIELD
        }
        previous: Any = getattr(task, "_task_provider_forced_fields", set())
        if isinstance(previous, (set, frozenset)):
            requested.update(previous)
        setattr(task, "_task_provider_forced_fields", requested)
        return requested

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
            iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                iso_datetime = datetime.datetime.fromisoformat(iso_value)
            except ValueError:
                iso_datetime = None
            if iso_datetime is not None and iso_datetime.tzinfo is not None:
                # TimePoint and the stored task model use naive local datetimes.
                # Convert the supplied instant first so later comparisons never
                # mix aware and naive values and the configured local zone stays
                # authoritative for civil dates and relative expressions.
                local_datetime = iso_datetime.astimezone(
                    TaskApplicationService._manager_timezone()
                ).replace(tzinfo=None)
                return TimePoint(local_datetime)

            if field == "start":
                is_relative = value.startswith(("+", "-", "now", "today", "tomorrow"))
                if not is_relative:
                    is_relative = value.count(":") == 1 and "T" not in value
                if not is_relative:
                    return TimePoint(datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M"))
            else:
                if "T" in value:
                    return TimePoint(datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M"))
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

    @staticmethod
    def _manager_timezone() -> datetime.tzinfo:
        configured = os.environ.get("TZ")
        if configured:
            try:
                return ZoneInfo(configured.removeprefix(":"))
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
