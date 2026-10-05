"""RFC 9457 problem responses for authenticated HTTP API requests."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import urlsplit

from aiohttp import web


_TITLES = {
    400: "Invalid request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Resource not found",
    405: "Method not allowed",
    406: "Not acceptable",
    409: "Operation conflict",
    413: "Request too large",
    415: "Unsupported media type",
    500: "Internal server error",
    503: "Service unavailable",
}

_REDACTION_MARKER = "[redactado]"
_AUTHORIZATION_VALUE = 'Bearer realm="api"'
_ABSOLUTE_URL = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>\"']+")
_URL_QUERY = re.compile(r"\?[^\s<>\"']*")
_AUTHORIZATION_HEADER = re.compile(r"(?i)\bauthorization\s*:\s*[^\r\n]*")
_BEARER_CREDENTIAL = re.compile(r"(?i)(\bBearer[ \t]+)[^\s,;]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:authorization|http[_-]?token|telegram[_-]?bot[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|token|api[_-]?key|password|secret)"
    r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_ALLOWED_METHODS = {"GET", "HEAD", "POST", "PATCH", "OPTIONS"}
_ALLOWED_WRITE_PHASES = {
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
_RESOURCE_KINDS = {"task", "project"}
_RESOURCE_NAMES = {"task", "project", "statistics"}


def safe_detail(value: str, token: str) -> str:
    """Remove credentials and URL data before text reaches a diagnostic sink."""
    detail = _AUTHORIZATION_HEADER.sub(_REDACTION_MARKER, value)
    detail = _ABSOLUTE_URL.sub(_REDACTION_MARKER, detail)
    detail = _URL_QUERY.sub(_REDACTION_MARKER, detail)
    if token and token != _REDACTION_MARKER:
        detail = detail.replace(token, _REDACTION_MARKER)
    detail = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{_REDACTION_MARKER}", detail
    )
    detail = _BEARER_CREDENTIAL.sub(
        lambda match: match.group(1) + _REDACTION_MARKER,
        detail,
    )
    return "".join(
        character
        for character in detail
        if unicodedata.category(character) != "Cc"
    )


def _safe_link(value: Any, token: str) -> dict[str, str] | None:
    """Keep only generated, same-origin path links in structured evidence."""
    if not isinstance(value, Mapping) or set(value) != {"kind", "href"}:
        return None
    kind = value.get("kind")
    href = value.get("href")
    if not isinstance(kind, str) or kind not in _RESOURCE_KINDS or not isinstance(href, str):
        return None
    try:
        parsed = urlsplit(href)
    except ValueError:
        return None
    invalid_link = any((
        parsed.scheme,
        parsed.netloc,
        parsed.query,
        parsed.fragment,
        not parsed.path.startswith("/"),
        parsed.path.startswith("//"),
        safe_detail(href, token) != href,
        any(part in {".", ".."} for part in parsed.path.split("/")),
    ))
    if invalid_link:
        return None
    return {"kind": kind, "href": href}


def _safe_evidence(evidence: Mapping[str, Any], token: str) -> dict[str, Any]:
    """Copy only known scalar evidence and checked resource links."""
    result: dict[str, Any] = {}
    saved_count = evidence.get("savedCount")
    if isinstance(saved_count, int) and not isinstance(saved_count, bool) and saved_count >= 0:
        result["savedCount"] = saved_count

    resource = evidence.get("failedResource")
    if isinstance(resource, str) and resource in _RESOURCE_NAMES:
        result["failedResource"] = resource
    else:
        safe_resource = _safe_link(resource, token)
        if safe_resource is not None:
            result["failedResource"] = safe_resource

    uncertain_resource = _safe_link(evidence.get("uncertainResource"), token)
    if uncertain_resource is not None:
        result["uncertainResource"] = uncertain_resource

    saved_resources = evidence.get("savedResources")
    if isinstance(saved_resources, list):
        safe_resources = [
            safe_link
            for item in saved_resources
            if (safe_link := _safe_link(item, token)) is not None
        ]
        if safe_resources:
            result["savedResources"] = safe_resources

    write_phase = evidence.get("writePhase")
    if isinstance(write_phase, str) and write_phase in _ALLOWED_WRITE_PHASES:
        result["writePhase"] = write_phase
    write_replaced = evidence.get("writeReplaced")
    if isinstance(write_replaced, str) and write_replaced in {"true", "false", "unknown"}:
        result["writeReplaced"] = write_replaced
    return result


def problem_response(
    *,
    status: int,
    code: str,
    detail: str,
    request_id: str,
    instance: str,
    token: str,
    field: str | None = None,
    operation_id: str | None = None,
    effects_state: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    challenge_bearer: bool = False,
    headers: dict[str, str] | None = None,
) -> web.Response:
    """Build a secret-safe problem response with consistent correlation fields."""
    safe_code = re.sub(
        r"[^a-z0-9-]", "-", safe_detail(code, token).lower()
    ).strip("-") or "request-failed"
    body: dict[str, Any] = {
        "type": f"urn:elrikpiro:problem:{safe_code}",
        "title": safe_detail(_TITLES.get(status, "Request failed"), token),
        "status": status,
        "detail": safe_detail(detail, token),
        "instance": safe_detail(instance, token),
        "code": safe_code,
        "requestId": request_id,
    }
    safe_field = safe_detail(field, token) if field is not None else None
    if safe_field is not None and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", safe_field):
        body["field"] = safe_field
    if operation_id is not None:
        body["operationId"] = safe_detail(operation_id, token)
    if effects_state in {"none", "partial", "unknown"}:
        body["effectsState"] = effects_state
    if evidence:
        body.update(_safe_evidence(evidence, token))
    response_headers = {"Cache-Control": "no-store", "X-Request-ID": request_id}
    if challenge_bearer:
        response_headers["WWW-Authenticate"] = _AUTHORIZATION_VALUE
    if headers:
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            if name.casefold() == "www-authenticate" and value == _AUTHORIZATION_VALUE:
                response_headers["WWW-Authenticate"] = _AUTHORIZATION_VALUE
            elif name.casefold() == "allow" and isinstance(value, str):
                methods = [method.strip() for method in value.split(",")]
                if methods and all(method in _ALLOWED_METHODS for method in methods):
                    response_headers["Allow"] = ", ".join(methods)
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return web.Response(
        status=status,
        text=encoded,
        content_type="application/problem+json",
        headers=response_headers,
    )
