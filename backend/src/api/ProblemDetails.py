"""RFC 9457 problem responses for authenticated HTTP API requests."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Mapping

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
    415: "Unsupported media type",
    500: "Internal server error",
    503: "Service unavailable",
}


def safe_detail(value: str, token: str) -> str:
    """Redact a configured secret and bearer-shaped values from public text."""
    detail = value
    if token:
        detail = detail.replace(token, "[redacted]")
    detail = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [redacted]", detail)
    return "".join(
        character
        for character in detail
        if unicodedata.category(character) != "Cc"
    )


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
        "title": _TITLES.get(status, "Request failed"),
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
        for key, value in evidence.items():
            if key in {"savedCount", "savedResources", "failedResource", "uncertainResource", "writePhase", "writeReplaced"}:
                body[key] = value
    response_headers = {"Cache-Control": "no-store", "X-Request-ID": request_id}
    if challenge_bearer:
        response_headers["WWW-Authenticate"] = 'Bearer realm="api"'
    if headers:
        response_headers.update(headers)
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return web.Response(
        status=status,
        text=encoded,
        content_type="application/problem+json",
        headers=response_headers,
    )
