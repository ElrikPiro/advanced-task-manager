"""Authenticated, resource-oriented HTTP v1 adapter."""

from __future__ import annotations

import datetime
import copy
import json
import hmac
import re
import unicodedata
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, quote

from aiohttp import web

from src.api.ApiResources import ApiResources
from src.api.HttpInput import (
    HttpInputError,
    decode_request_path,
    normalize_api_prefix,
    require_exact_keys,
    require_json_object,
    validate_query,
)
from src.api.ProblemDetails import problem_response
from src.domain.errors import (
    AmbiguousResourceError,
    DomainError,
    OperationConflictError,
    OperationFailedError,
    OperationResultUnavailableError,
    ResourceConflictError,
    ResourceNotFoundError,
    ResourceReadError,
    UnsupportedOperationError,
    ValidationError,
)
from src.domain.models import AgendaQuery, OperationTarget, TaskView
from src.domain.models import OperationIntent, OperationResult
from src.MutationCoordinator import MutationCoordinatorClosed, OperationReceipt
from src.wrappers.TimeManagement import TimePoint

_OPERATION_ID_KEY: web.RequestKey[str] = web.RequestKey("operation-id", str)
_OPERATION_TYPE_KEY: web.RequestKey[str] = web.RequestKey("operation-type", str)
_OPERATION_TARGET_KEY: web.RequestKey[OperationTarget] = web.RequestKey(
    "operation-target", OperationTarget
)


class _HttpFailure(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        field: str | None = None,
        operation_id: str | None = None,
        effects_state: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.field = field
        self.operation_id = operation_id
        self.effects_state = effects_state
        self.headers = headers or {}


class HttpApiV1:
    """Expose one application service through the versioned HAL contract."""

    _CHANGE_FIELDS = {
        "description": "description",
        "context": "context",
        "start": "start",
        "due": "due",
        "severity": "severity",
        "totalCost": "total_cost",
        "calm": "calm",
        "raised": "raised",
        "waited": "waited",
    }
    _LEGACY_MUTATING_GETS = {
        "done",
        "set",
        "new",
        "schedule",
        "work",
        "snooze",
        "raise",
        "project",
        "next",
        "previous",
        "search",
    }

    def __init__(
        self,
        application_service: Any,
        token: str,
        prefix: str = "/api/v1",
        notification_history_store: Any | None = None,
    ) -> None:
        if application_service is None:
            raise ValueError("An application service is required")
        self.application_service = application_service
        self.token = token
        self.notification_history_store = notification_history_store
        self.prefix, self._prefix_segments = normalize_api_prefix(prefix)
        self.resources = ApiResources(
            application_service,
            prefix=self.prefix,
            token=token,
            notification_history_store=notification_history_store,
        )

    def create_app(self) -> web.Application:
        """Create an aiohttp app for production or isolated TestClient use."""
        app = web.Application(client_max_size=1_048_576)
        app.router.add_route("*", "/{tail:.*}", self.handle_request)
        return app

    async def handle_request(self, request: web.BaseRequest) -> web.Response:
        request_id = str(uuid.uuid4())
        operation_id: str | None = None
        try:
            if not self._authorized(request):
                raise _HttpFailure(
                    401,
                    "authentication-required",
                    "A valid Bearer token is required",
                    headers={"WWW-Authenticate": 'Bearer realm="api"'},
                )
            self._validate_accept(request)
            self._validate_raw_query(request)
            path_segments = decode_request_path(request)
            remainder = self._route_segments(path_segments)
            if remainder is None:
                if self._is_unsupported_version(path_segments):
                    raise _HttpFailure(
                        404,
                        "unsupported-version",
                        "This API version is not supported",
                    )
                self._reject_legacy_path(request, path_segments)
                if path_segments[-1:] == ("notifications",):
                    raise _HttpFailure(
                        404,
                        "notifications-unavailable",
                        "The notification resource is not available",
                    )
                raise _HttpFailure(404, "not-found", "The requested resource was not found")
            response, operation_id = await self._dispatch(request, remainder)
            return self._decorate(response, request_id)
        except HttpInputError as error:
            operation_id = self._known_operation_id(request, operation_id)
            return self._problem(
                request_id,
                400,
                error.code,
                error.detail,
                field=error.field,
                operation_id=operation_id,
                effects_state="none",
            )
        except _HttpFailure as error:
            operation_id = self._known_operation_id(request, operation_id)
            return self._problem(
                request_id,
                error.status,
                error.code,
                error.detail,
                field=error.field,
                operation_id=error.operation_id or operation_id,
                effects_state=error.effects_state or "none",
                headers=error.headers,
            )
        except DomainError as error:
            operation_id = self._known_operation_id(request, operation_id)
            status, detail = self._domain_problem(error)
            domain_field = self._domain_field(error)
            field = self._public_field_name(domain_field) if domain_field is not None else None
            if status == 400 and domain_field is not None:
                detail = self._validation_detail(domain_field)
            return self._problem(
                request_id,
                status,
                error.code,
                detail,
                field=field,
                operation_id=operation_id,
                effects_state=error.effects_state,
                evidence=self._domain_evidence(
                    error,
                    self._known_operation_target(request),
                    request.get(_OPERATION_TYPE_KEY),
                ),
            )
        except MutationCoordinatorClosed:
            operation_id = self._known_operation_id(request, operation_id)
            return self._problem(
                request_id,
                503,
                "service-unavailable",
                "The service is not accepting operations",
                operation_id=operation_id,
                effects_state="none",
            )
        except web.HTTPRequestEntityTooLarge:
            return self._problem(
                request_id, 400, "request-too-large", "The request body is too large"
            )
        except Exception as error:
            operation_id = self._known_operation_id(request, operation_id)
            error_code = getattr(error, "code", None)
            if error_code == "notification-history-unavailable":
                return self._problem(
                    request_id,
                    503,
                    "notification-history-unavailable",
                    "Notification history is unavailable",
                    effects_state="none",
                )
            safe_codes = {
                "operation-failed",
                "operation-id-conflict",
                "operation-result-unavailable",
                "resource-read-failed",
                "notification-history-invalid",
                "calculation-failed",
                "invalid-resource-data",
            }
            code = error_code if isinstance(error_code, str) and error_code in safe_codes else "internal-error"
            effects_state = getattr(error, "effects_state", None)
            if effects_state not in {"none", "partial", "unknown"}:
                effects_state = "unknown" if operation_id is not None else None
            detail = (
                "The operation failed; review its effects before retrying"
                if code == "operation-failed"
                else "The request could not be completed"
            )
            return self._problem(
                request_id,
                500,
                code,
                detail,
                operation_id=operation_id,
                effects_state=effects_state,
                evidence=self._domain_evidence(
                    error,
                    self._known_operation_target(request),
                    request.get(_OPERATION_TYPE_KEY),
                ),
            )

    def _authorized(self, request: web.BaseRequest) -> bool:
        if not self.token:
            return False
        values = request.headers.getall("Authorization", [])
        if len(values) != 1:
            return False
        expected = f"Bearer {self.token}"
        try:
            return hmac.compare_digest(
                values[0].encode("utf-8"), expected.encode("utf-8")
            )
        except (UnicodeEncodeError, TypeError):
            return False

    def _route_segments(self, path_segments: tuple[str, ...]) -> tuple[str, ...] | None:
        if path_segments[: len(self._prefix_segments)] != self._prefix_segments:
            return None
        return path_segments[len(self._prefix_segments):]

    def _is_unsupported_version(self, path_segments: tuple[str, ...]) -> bool:
        deployment = self._prefix_segments[:-2]
        if path_segments[: len(deployment)] != deployment:
            return False
        version_index = len(deployment) + 1
        if len(path_segments) <= version_index:
            return False
        version = path_segments[version_index]
        return path_segments[len(deployment)] == "api" and re.fullmatch(r"v[0-9]+", version) is not None and version != "v1"

    def _reject_legacy_path(
        self, request: web.BaseRequest, path_segments: tuple[str, ...]
    ) -> None:
        if request.method != "GET" or not path_segments:
            return
        first = path_segments[0]
        if first in self._LEGACY_MUTATING_GETS or any(
            first.startswith(prefix) for prefix in ("task_", "heuristic_", "filter_", "algorithm_")
        ):
            raise _HttpFailure(
                404,
                "legacy-route-retired",
                "This command route is retired; use the versioned resource API",
            )

    def _validate_accept(self, request: web.BaseRequest) -> None:
        header = request.headers.get("Accept")
        if not header:
            return
        supported = {
            "application/hal+json",
            "application/problem+json",
            "application/json",
            "application/*",
            "*/*",
        }
        for item in header.split(","):
            pieces = [piece.strip() for piece in item.split(";")]
            media_type = pieces[0].lower()
            quality = 1.0
            for parameter in pieces[1:]:
                name, separator, value = parameter.partition("=")
                if separator and name.strip().lower() == "q":
                    try:
                        quality = float(value.strip())
                    except ValueError:
                        quality = 0.0
            if quality > 0 and media_type in supported:
                return
        raise _HttpFailure(
            406,
            "not-acceptable",
            "The API returns HAL JSON and Problem Details JSON",
        )

    @staticmethod
    def _validate_raw_query(request: web.BaseRequest) -> None:
        raw_query = request.raw_path.partition("?")[2]
        if not raw_query:
            return
        if re.search(r"%(?![0-9A-Fa-f]{2})", raw_query):
            raise HttpInputError("invalid-query-encoding", "The query encoding is invalid")
        try:
            parse_qsl(
                raw_query,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=100,
            )
        except (UnicodeDecodeError, ValueError) as error:
            raise HttpInputError("invalid-query-encoding", "The query encoding is invalid") from error

    async def _dispatch(
        self, request: web.BaseRequest, path: tuple[str, ...]
    ) -> tuple[web.Response, str | None]:
        if not path:
            self._require_method(request, {"GET"})
            self._require_no_query(request)
            return self._hal(self.resources.read_root()), None

        if path == ("tasks",):
            if request.method == "GET":
                view = self._task_view(request)
                return self._hal(self.resources.read_tasks(view)), None
            self._require_method(request, {"GET"})

        if len(path) == 2 and path[0] == "tasks":
            if request.method == "GET":
                self._require_no_query(request)
                return self._hal(self.resources.read_task(path[1])), None
            if request.method == "PATCH":
                self._require_request_media(request, "application/merge-patch+json")
                self._require_no_query(request)
                document = await self._read_json_object(request)
                changes = self._map_changes(document)
                target = OperationTarget("task", path[1])
                parameters = {"changes": changes}
                request[_OPERATION_TARGET_KEY] = target
                request[_OPERATION_TYPE_KEY] = "edit-task"
                self.application_service.validate_operation_structure(
                    "edit-task", target, parameters
                )
                operation_id = str(uuid.uuid4())
                request[_OPERATION_ID_KEY] = operation_id
                result = await self.application_service.submit_operation_async(
                    operation_id, "edit-task", target, parameters
                )
                return self._hal(self.resources.task_resource(result.value)), operation_id
            self._require_method(request, {"GET", "PATCH"})

        if path == ("agenda",):
            self._require_method(request, {"GET"})
            query_values = validate_query(request.query, {"day", "heuristic"})
            day_value = query_values.get("day", [None])[0]
            heuristic = query_values.get("heuristic", ["Remaining Effort(1)"])[0]
            if day_value is None:
                day = TimePoint.today()
            else:
                try:
                    parsed_day = datetime.datetime.strptime(day_value, "%Y-%m-%d")
                except ValueError as error:
                    raise HttpInputError("invalid-query-parameter", "day must use YYYY-MM-DD", field="day") from error
                day = TimePoint(parsed_day)
            if not heuristic:
                raise HttpInputError("invalid-query-parameter", "heuristic must be a name", field="heuristic")
            return self._hal(self.resources.read_agenda(AgendaQuery(day=day, heuristic=heuristic))), None

        if path == ("statistics",):
            self._require_method(request, {"GET"})
            return self._hal(self.resources.read_statistics(self._task_view(request))), None

        if path == ("notifications",):
            self._require_method(request, {"GET"})
            self._require_no_query(request)
            if self.notification_history_store is None:
                raise _HttpFailure(
                    503,
                    "notification-history-unavailable",
                    "Notification history is not configured",
                )
            return self._hal(self.resources.read_notifications()), None

        if path in {("events",), ("strategies",)}:
            self._require_method(request, {"GET"})
            self._require_no_query(request)
            if path[0] == "events":
                return self._hal(self.resources.read_events()), None
            return self._hal(self.resources.read_strategies()), None

        if path == ("projects",):
            self._require_method(request, {"GET"})
            query_values = validate_query(request.query, {"status"})
            status = query_values.get("status", ["open"])[0]
            if not status:
                raise HttpInputError("invalid-query-parameter", "status must be a name", field="status")
            return self._hal(self.resources.read_projects(status)), None

        if len(path) == 2 and path[0] == "projects":
            self._require_method(request, {"GET"})
            self._require_no_query(request)
            return self._hal(self.resources.read_project(path[1])), None

        if path == ("operations",):
            if request.method != "POST":
                self._require_method(request, {"POST"})
            self._require_request_media(request, "application/json")
            self._require_no_query(request)
            operation_id, operation_type, target, parameters = await self._parse_operation_request(request)
            result = await self._submit_operation(operation_id, operation_type, target, parameters)
            receipt = self._successful_receipt(
                operation_id, operation_type, target, parameters, result
            )
            payload = self.resources.operation_resource(receipt)
            return self._hal(payload, status=201, headers={"Location": self._operation_href(operation_id)}), operation_id

        if len(path) == 2 and path[0] == "operations":
            self._require_method(request, {"GET"})
            self._require_no_query(request)
            operation_id = self._normalize_uuid(path[1], field="id")
            request[_OPERATION_ID_KEY] = operation_id
            return self._hal(self.resources.read_operation(operation_id)), None

        raise _HttpFailure(404, "not-found", "The requested resource was not found")

    def _task_view(self, request: web.BaseRequest) -> TaskView:
        query_values = validate_query(
            request.query,
            {"page", "pageSize", "filters", "heuristic", "algorithm", "search"},
            repeatable={"filters", "search"},
        )
        page = self._positive_integer(query_values.get("page", ["1"])[0], "page")
        page_size = self._positive_integer(query_values.get("pageSize", ["5"])[0], "pageSize")
        filters = tuple(query_values.get("filters", ["All active task filter"]))
        search = tuple(query_values.get("search", []))
        heuristic = query_values.get("heuristic", ["Remaining Effort(1)"])[0]
        algorithm = query_values.get("algorithm", ["GTD Algorithm"])[0]
        if any(not item for item in filters):
            raise HttpInputError("invalid-query-parameter", "filters must contain names", field="filters")
        if not heuristic or not algorithm:
            raise HttpInputError("invalid-query-parameter", "algorithm and heuristic must be names")
        return TaskView(
            filters=filters,
            page=page,
            page_size=page_size,
            algorithm=algorithm,
            heuristic=heuristic,
            search=search,
        )

    @staticmethod
    def _positive_integer(value: str, field: str) -> int:
        if not re.fullmatch(r"[0-9]+", value):
            raise HttpInputError(
                "invalid-query-parameter", f"{field} must be a positive integer", field=field
            )
        try:
            parsed = int(value)
        except ValueError as error:
            raise HttpInputError(
                "invalid-query-parameter", f"{field} must be a positive integer", field=field
            ) from error
        if parsed < 1:
            raise HttpInputError(
                "invalid-query-parameter", f"{field} must be a positive integer", field=field
            )
        return parsed

    @staticmethod
    def _require_no_query(request: web.BaseRequest) -> None:
        if request.query:
            raise HttpInputError(
                "unknown-query-parameter",
                "This resource does not accept query parameters",
                field=sorted(request.query.keys())[0],
            )

    @staticmethod
    def _require_method(request: web.BaseRequest, allowed: set[str]) -> None:
        if request.method not in allowed:
            allowed_header = ", ".join(sorted(allowed))
            raise _HttpFailure(
                405,
                "method-not-allowed",
                "The HTTP method is not supported for this resource",
                headers={"Allow": allowed_header},
            )

    @staticmethod
    def _require_request_media(request: web.BaseRequest, expected: str) -> None:
        media_values = request.headers.getall("Content-Type", [])
        valid_media = len(media_values) == 1
        if valid_media:
            media_parts = media_values[0].split(";")
            valid_media = media_parts[0].strip().lower() == expected
            parameters = media_parts[1:]
            if len(parameters) > 1:
                valid_media = False
            elif parameters:
                valid_media = valid_media and re.fullmatch(
                    r'\s*charset\s*=\s*(?:utf-8|"utf-8")\s*',
                    parameters[0],
                    flags=re.IGNORECASE,
                ) is not None
        if not valid_media:
            raise _HttpFailure(
                415,
                "unsupported-media-type",
                f"This operation requires {expected}",
            )

    async def _read_json_object(self, request: web.BaseRequest) -> dict[str, Any]:
        return require_json_object(await request.read())

    async def _parse_operation_request(
        self, request: web.BaseRequest
    ) -> tuple[str, str, OperationTarget, dict[str, Any]]:
        expected_type = "application/merge-patch+json" if request.method == "PATCH" else "application/json"
        self._require_request_media(request, expected_type)
        self._require_no_query(request)
        body = await self._read_json_object(request)
        require_exact_keys(body, {"id", "type", "target", "parameters"}, {"id", "type", "target", "parameters"}, field="body")
        operation_id = self._normalize_uuid(body["id"], field="id")
        request[_OPERATION_ID_KEY] = operation_id
        operation_type = body["type"]
        if not isinstance(operation_type, str) or not operation_type:
            raise HttpInputError("invalid-field", "type must be a non-empty string", field="type")
        target = self._parse_target(body["target"])
        request[_OPERATION_TYPE_KEY] = operation_type
        request[_OPERATION_TARGET_KEY] = target
        raw_parameters = body["parameters"]
        if not isinstance(raw_parameters, dict):
            raise HttpInputError("invalid-field", "parameters must be an object", field="parameters")
        parameters = self._map_operation_parameters(operation_type, raw_parameters)
        self._validate_operation_target_shape(operation_type, target)
        return operation_id, operation_type, target, parameters

    def _parse_target(self, value: Any) -> OperationTarget:
        if not isinstance(value, dict):
            raise HttpInputError("invalid-field", "target must be an object", field="target")
        require_exact_keys(value, {"kind"}, {"kind", "id"}, field="target")
        kind = value["kind"]
        allowed_kinds: set[str] = {"task", "tasks", "event", "project"}
        if not isinstance(kind, str) or kind not in allowed_kinds:
            raise HttpInputError("invalid-field", "target.kind is invalid", field="target.kind")
        typed_kind = cast(Literal["task", "tasks", "event", "project"], kind)
        target_id = value.get("id")
        if target_id is not None and not isinstance(target_id, str):
            raise HttpInputError("invalid-field", "target.id must be a string", field="target.id")
        if typed_kind == "tasks":
            if "id" in value:
                raise HttpInputError(
                    "invalid-field", "The tasks collection target does not accept an id", field="target.id"
                )
        elif not target_id:
            raise HttpInputError("invalid-field", "target.id is required", field="target.id")
        return OperationTarget(typed_kind, target_id)

    def _map_operation_parameters(
        self, operation_type: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if operation_type == "create-task":
            self._reject_unknown_parameters(parameters, {"description", "context", "totalCost"})
            create_parameters = dict(parameters)
            if "totalCost" in create_parameters:
                create_parameters["total_cost"] = self._pomodoro_amount(
                    create_parameters.pop("totalCost"), "parameters.totalCost"
                )
            return create_parameters
        if operation_type == "edit-task":
            allowed = {"changes", "effortDelta"}
            unknown = set(parameters) - allowed
            if unknown:
                raise HttpInputError(
                    "unknown-field", "The operation contains an unknown parameter", field="parameters"
                )
            edit_parameters: dict[str, Any] = {}
            if "changes" in parameters:
                if not isinstance(parameters["changes"], dict):
                    raise HttpInputError("invalid-field", "changes must be an object", field="parameters.changes")
                edit_parameters["changes"] = self._map_changes(parameters["changes"])
            if "effortDelta" in parameters:
                edit_parameters["effort_delta"] = self._duration_value(
                    parameters["effortDelta"], "parameters.effortDelta", allow_pomodoro_object=True
                )
            return edit_parameters
        if operation_type == "schedule-task":
            self._reject_unknown_parameters(parameters, {"effortPerDay"})
            schedule_parameters = dict(parameters)
            if "effortPerDay" in schedule_parameters:
                schedule_parameters["effort_per_day"] = schedule_parameters.pop("effortPerDay")
            return schedule_parameters
        if operation_type in {"record-work", "snooze-task"}:
            self._reject_unknown_parameters(parameters, {"duration"})
            if "duration" in parameters and not isinstance(parameters["duration"], str):
                raise HttpInputError(
                    "invalid-field", "duration must be a string", field="parameters.duration"
                )
        if operation_type in {"complete-task", "raise-event", "close-project", "hold-project"}:
            self._reject_unknown_parameters(parameters, set())
        if operation_type == "open-project":
            self._reject_unknown_parameters(parameters, {"description"})
        if operation_type == "edit-project-content":
            self._reject_unknown_parameters(
                parameters, {"action", "line", "position", "content", "description"}
            )
        return dict(parameters)

    @staticmethod
    def _reject_unknown_parameters(parameters: Mapping[str, Any], allowed: set[str]) -> None:
        unknown = set(parameters) - allowed
        if unknown:
            field = sorted(unknown)[0]
            raise HttpInputError(
                "unknown-field",
                "The operation contains an unknown parameter",
                field=f"parameters.{field}",
            )

    @staticmethod
    def _validate_operation_target_shape(operation_type: str, target: OperationTarget) -> None:
        if operation_type == "create-task" and target.kind != "tasks":
            raise HttpInputError(
                "invalid-target", "create-task targets the tasks collection", field="target.kind"
            )
        if operation_type in {
            "edit-task",
            "complete-task",
            "schedule-task",
            "record-work",
            "snooze-task",
        } and target.kind != "task":
            raise HttpInputError(
                "invalid-target", "This operation requires a task target", field="target.kind"
            )
        if operation_type == "raise-event" and target.kind != "event":
            raise HttpInputError(
                "invalid-target", "raise-event requires an event target", field="target.kind"
            )
        if operation_type in {
            "open-project",
            "close-project",
            "hold-project",
            "edit-project-content",
        } and target.kind != "project":
            raise HttpInputError(
                "invalid-target", "This operation requires a project target", field="target.kind"
            )

    def _map_changes(self, changes: dict[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - set(self._CHANGE_FIELDS)
        if unknown:
            field = sorted(unknown)[0]
            raise HttpInputError(
                "unknown-field", "The task field is unknown or read-only", field=field
            )
        mapped: dict[str, Any] = {}
        for public_name, value in changes.items():
            field_name = self._CHANGE_FIELDS[public_name]
            if value is None and public_name not in {"raised", "waited"}:
                raise HttpInputError(
                    "invalid-field", "Null is allowed only for optional event fields", field=public_name
                )
            if public_name == "totalCost":
                value = self._pomodoro_amount(value, public_name)
            elif public_name in {"start", "due"} and isinstance(value, str):
                value = self._date_value(value, public_name)
            mapped[field_name] = value
        return mapped

    @staticmethod
    def _pomodoro_amount(value: Any, field: str) -> str:
        if not isinstance(value, dict) or set(value) != {"value", "unit"}:
            raise HttpInputError(
                "invalid-effort", "Effort must include a decimal value and unit", field=field
            )
        if value["unit"] != "pomodoro" or not isinstance(value["value"], str) or len(value["value"]) > 64 or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value["value"]) is None:
            raise HttpInputError(
                "invalid-effort", "Effort unit must be pomodoro and value must be decimal text", field=field
            )
        try:
            amount = Decimal(value["value"])
        except InvalidOperation as error:
            raise HttpInputError(
                "invalid-effort", "Effort value must be a finite decimal", field=field
            ) from error
        if not amount.is_finite():
            raise HttpInputError(
                "invalid-effort", "Effort value must be a finite decimal", field=field
            )
        return f"{format(amount, 'f')}p"

    def _duration_value(self, value: Any, field: str, *, allow_pomodoro_object: bool) -> Any:
        if isinstance(value, str):
            return value
        if allow_pomodoro_object:
            return self._pomodoro_amount(value, field)
        raise HttpInputError("invalid-duration", "Duration must be a string", field=field)

    @staticmethod
    def _date_value(value: str, field: str) -> str | TimePoint:
        # Retain the established relative expressions and short legacy forms.
        if re.match(r"^[+-]|^(now|today|tomorrow)(?:$|;)", value):
            return value
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
            return value
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
        if "T" not in value:
            return value
        try:
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise HttpInputError(
                "invalid-date", "Dates must be ISO 8601 instants or supported relative expressions", field=field
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise HttpInputError(
                "invalid-date", "ISO 8601 instants must include a UTC offset", field=field
            )
        return value

    @staticmethod
    def _normalize_uuid(value: Any, *, field: str) -> str:
        if not isinstance(value, str):
            raise HttpInputError("invalid-uuid", "The value must be a UUID", field=field)
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError, TypeError) as error:
            raise HttpInputError("invalid-uuid", "The value must be a UUID", field=field) from error

    async def _submit_operation(
        self,
        operation_id: str,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
    ) -> OperationResult:
        self.application_service.validate_operation_structure(operation_type, target, parameters)
        result = await self.application_service.submit_operation_async(
            operation_id, operation_type, target, parameters
        )
        return cast(OperationResult, result)

    @staticmethod
    def _successful_receipt(
        operation_id: str,
        operation_type: str,
        target: OperationTarget,
        parameters: Mapping[str, Any],
        result: OperationResult,
    ) -> OperationReceipt:
        """Build the POST response from its completed result without a registry read."""
        intent = OperationIntent(
            operation_type,
            copy.deepcopy(target),
            copy.deepcopy(dict(parameters)),
        )
        return OperationReceipt(operation_id, intent, "succeeded", copy.deepcopy(result))

    def _operation_href(self, operation_id: str) -> str:
        return f"{self.prefix}/operations/{self._segment(operation_id)}"

    @staticmethod
    def _segment(value: str) -> str:
        if value == ".":
            return "%2E"
        if value == "..":
            return "%2E%2E"
        return quote(value, safe="")

    @staticmethod
    def _known_operation_id(request: web.BaseRequest, current: str | None) -> str | None:
        candidate = request.get(_OPERATION_ID_KEY)
        return candidate if isinstance(candidate, str) else current

    @staticmethod
    def _hal(
        payload: Any,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> web.Response:
        if not isinstance(payload, Mapping):
            raise TypeError("HAL resources must be JSON objects")
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        response_headers = {"Cache-Control": "no-store"}
        if headers:
            response_headers.update(headers)
        return web.Response(
            status=status,
            text=encoded,
            content_type="application/hal+json",
            headers=response_headers,
        )

    def _problem(
        self,
        request_id: str,
        status: int,
        code: str,
        detail: str,
        *,
        field: str | None = None,
        operation_id: str | None = None,
        effects_state: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> web.Response:
        challenge = status == 401
        return problem_response(
            status=status,
            code=code,
            detail=detail,
            request_id=request_id,
            instance=self.prefix,
            token=self.token,
            field=field,
            operation_id=operation_id,
            effects_state=effects_state,
            evidence=evidence,
            challenge_bearer=challenge,
            headers=headers,
        )

    @staticmethod
    def _decorate(response: web.Response, request_id: str) -> web.Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _domain_field(error: DomainError) -> str | None:
        field = error.details.get("field")
        if isinstance(field, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", field):
            return field
        return None

    @staticmethod
    def _known_operation_target(request: web.BaseRequest) -> OperationTarget | None:
        return request.get(_OPERATION_TARGET_KEY)

    @staticmethod
    def _public_field_name(field: str) -> str:
        return {
            "total_cost": "totalCost",
            "effort_delta": "effortDelta",
            "effort_per_day": "effortPerDay",
            "page_size": "pageSize",
            "operation_id": "id",
            "operation_type": "type",
        }.get(field, field)

    @classmethod
    def _validation_detail(cls, field: str) -> str:
        public_name = cls._public_field_name(field)
        rules = {
            "description": "description must be a non-empty string",
            "context": "context must be supported by the configured task categories",
            "start": "start must be an ISO 8601 instant with offset or a supported time expression",
            "due": "due must be an ISO 8601 instant with offset or a supported time expression",
            "severity": "severity must be a finite number",
            "totalCost": "totalCost must be a finite supported duration",
            "calm": "calm must be a boolean",
            "raised": "raised must be text or null",
            "waited": "waited must be text or null",
            "effortDelta": "effortDelta must be a supported finite duration",
            "effortPerDay": "effortPerDay must be a supported duration expression",
            "algorithm": "algorithm must name a supported algorithm",
            "heuristic": "heuristic must name a supported heuristic",
            "page": "page must be a positive integer",
            "pageSize": "pageSize must be a positive integer",
            "day": "day must use the YYYY-MM-DD format",
            "status": "status must be supported for this resource",
            "action": "action must be supported for the target resource",
            "line": "line or position must be a positive integer",
            "position": "line or position must be a positive integer",
            "content": "content must be valid for the selected action",
            "type": "type must name a supported operation",
            "operation_id": "id must be a valid UUID",
            "target": "target must identify the resource required by the operation type",
            "parameters": "parameters do not match the selected operation type",
        }
        return rules.get(
            public_name,
            f"The value supplied for {public_name} does not meet its field requirements",
        )

    def _domain_evidence(
        self,
        error: Any,
        target: OperationTarget | None,
        operation_type: Any,
    ) -> dict[str, Any] | None:
        effects_state = getattr(error, "effects_state", None)
        if effects_state not in {"none", "partial", "unknown"}:
            return None
        raw_details = getattr(error, "details", {})
        details = raw_details if isinstance(raw_details, Mapping) else {}
        evidence: dict[str, Any] = {}
        saved_count_value = details.get("saved_count")
        if isinstance(saved_count_value, str) and saved_count_value.isdecimal():
            try:
                saved_count = int(saved_count_value)
            except ValueError:
                saved_count = -1
            if saved_count >= 0:
                evidence["savedCount"] = saved_count

        resource = details.get("failed_resource") or details.get("resource")
        phase = details.get("write_phase") or details.get("phase")
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
        if isinstance(phase, str) and phase in allowed_phases:
            evidence["writePhase"] = phase
        replaced = details.get("write_replaced")
        if isinstance(replaced, str) and replaced in {"true", "false", "unknown"}:
            evidence["writeReplaced"] = replaced

        target_kind: str | None = None
        if isinstance(operation_type, str) and operation_type in {
            "create-task",
            "edit-task",
            "complete-task",
            "schedule-task",
            "record-work",
            "snooze-task",
        }:
            target_kind = "task"
        elif isinstance(operation_type, str) and operation_type in {
            "open-project",
            "close-project",
            "hold-project",
            "edit-project-content",
        }:
            target_kind = "project"
        elif isinstance(operation_type, str) and operation_type == "raise-event":
            target_kind = "task"
        elif target is not None and target.kind in {"task", "project"}:
            target_kind = target.kind

        saved_ids: list[str] = []
        serialized_saved_ids = details.get("saved_ids")
        if isinstance(serialized_saved_ids, str):
            try:
                parsed_saved_ids = json.loads(serialized_saved_ids)
            except (json.JSONDecodeError, ValueError):
                parsed_saved_ids = []
            if isinstance(parsed_saved_ids, list):
                saved_ids = [value for value in parsed_saved_ids if isinstance(value, str)]
        saved_resources = self._resource_links(target_kind, saved_ids)
        if saved_resources:
            evidence["savedResources"] = saved_resources

        failed_resource_id: str | None = None
        failed_id = details.get("failed_id")
        if isinstance(failed_id, str):
            failed_resource_links = self._resource_links(target_kind, [failed_id])
            if failed_resource_links:
                evidence["failedResource"] = failed_resource_links[0]
                failed_resource_id = failed_id
        if "failedResource" not in evidence:
            if isinstance(resource, str) and resource in {"task", "project", "statistics"}:
                evidence["failedResource"] = resource

        uncertain_id = details.get("uncertain_id")
        write_uncertain = effects_state == "unknown" or replaced == "unknown"
        if not isinstance(uncertain_id, str) and write_uncertain:
            uncertain_id = failed_resource_id
            if uncertain_id is None and target is not None:
                if target.kind in {"task", "project"} and target.kind == target_kind:
                    uncertain_id = target.id
        if isinstance(uncertain_id, str):
            uncertain_links = self._resource_links(target_kind, [uncertain_id])
            if uncertain_links:
                evidence["uncertainResource"] = uncertain_links[0]
        return evidence or None

    def _resource_links(self, kind: str | None, identifiers: list[str]) -> list[dict[str, str]]:
        if kind not in {"task", "project"}:
            return []
        collection = "tasks" if kind == "task" else "projects"
        links: list[dict[str, str]] = []
        for identifier in identifiers:
            if not identifier or len(identifier) > 4096:
                continue
            if any(unicodedata.category(char) == "Cc" for char in identifier):
                continue
            if re.search(r"(?i)bearer\s+[^\s,;]+", identifier):
                continue
            if self.token and self.token in identifier:
                continue
            href = f"{self.prefix}/{collection}/{self._segment(identifier)}"
            links.append({"kind": kind, "href": href})
        return links

    @staticmethod
    def _domain_problem(error: DomainError) -> tuple[int, str]:
        if error.code == "notification-history-unavailable":
            return 503, "Notification history is unavailable"
        if error.code == "notification-history-invalid":
            return 500, "Notification history could not be read"
        if isinstance(error, ValidationError):
            return 400, "The request contains invalid fields or values"
        if isinstance(error, OperationConflictError):
            return 409, "The operation identifier is already associated with another intent"
        if isinstance(error, (AmbiguousResourceError, ResourceConflictError)):
            return 409, "The requested resource conflicts with current data"
        if isinstance(error, (ResourceNotFoundError, OperationResultUnavailableError)):
            return 404, "The requested resource or retained result was not found"
        if isinstance(error, UnsupportedOperationError):
            return 400, "The requested operation type is not supported"
        if isinstance(error, OperationFailedError):
            return 500, "The operation failed; review its effects before retrying"
        if isinstance(error, ResourceReadError):
            return 500, "The requested resource could not be read"
        return 500, "The request could not be completed"
