"""Strict parsing helpers for the resource HTTP API."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable, Mapping
from urllib.parse import unquote_to_bytes

from aiohttp import web


class HttpInputError(ValueError):
    """An invalid transport value that can be safely returned to a client."""

    def __init__(self, code: str, detail: str, *, field: str | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.field = field


def normalize_api_prefix(value: str) -> tuple[str, tuple[str, ...]]:
    """Validate a configured mount path and return its decoded segments."""
    if not isinstance(value, str):
        raise ValueError("HTTP_API_PREFIX must be an absolute API path")
    if not value.startswith("/") or "?" in value or "#" in value:
        raise ValueError("HTTP_API_PREFIX must be an absolute API path")
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise ValueError("HTTP_API_PREFIX must be an absolute API path")
    if "\\" in value or "%" in value:
        raise ValueError("HTTP_API_PREFIX must not contain encoded path data")
    segments = value.strip("/").split("/")
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise ValueError("HTTP_API_PREFIX contains an invalid path segment")
    if any(re.fullmatch(r"[A-Za-z0-9._~-]+", segment) is None for segment in segments):
        raise ValueError("HTTP_API_PREFIX contains a path segment that cannot be linked safely")
    if len(segments) < 2 or segments[-2:] != ["api", "v1"]:
        raise ValueError("HTTP_API_PREFIX must end in /api/v1")
    prefix = "/" + "/".join(segments)
    return prefix, tuple(segments)


def decode_request_path(request: web.BaseRequest) -> tuple[str, ...]:
    """Decode each raw URL path segment once, without splitting decoded IDs."""
    raw_path = request.raw_path.partition("?")[0]
    if not raw_path.startswith("/") or "\\" in raw_path:
        raise HttpInputError("invalid-path", "The request path is invalid")
    raw_segments = raw_path[1:].split("/")
    if raw_segments and raw_segments[-1] == "":
        raw_segments.pop()
    if any(not segment for segment in raw_segments):
        raise HttpInputError("invalid-path", "The request path contains an empty segment")

    decoded: list[str] = []
    for segment in raw_segments:
        if re.search(r"%(?![0-9A-Fa-f]{2})", segment):
            raise HttpInputError("invalid-path-encoding", "The request path encoding is invalid")
        try:
            value = unquote_to_bytes(segment).decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise HttpInputError(
                "invalid-path-encoding", "The request path encoding is invalid"
            ) from error
        if "\x00" in value or any(ord(character) < 32 for character in value):
            raise HttpInputError("invalid-path", "The request path contains an invalid character")
        decoded.append(value)
    return tuple(decoded)


def validate_query(
    query: Any,
    allowed: Iterable[str],
    *,
    repeatable: Iterable[str] = (),
) -> dict[str, list[str]]:
    """Reject unknown keys and duplicate scalar query parameters."""
    allowed_set = set(allowed)
    repeatable_set = set(repeatable)
    unknown = set(query.keys()) - allowed_set
    if unknown:
        field = sorted(unknown)[0]
        raise HttpInputError(
            "unknown-query-parameter",
            "The request contains an unknown query parameter",
            field=field,
        )

    values_by_key: dict[str, list[str]] = {}
    for key in allowed_set:
        values = list(query.getall(key, []))
        if len(values) > 1 and key not in repeatable_set:
            raise HttpInputError(
                "duplicate-query-parameter",
                "A scalar query parameter may be supplied only once",
                field=key,
            )
        if values:
            values_by_key[key] = values
    return values_by_key


def require_json_object(raw: bytes, *, field: str = "body") -> dict[str, Any]:
    """Parse a JSON object while rejecting duplicate keys and NaN/Infinity."""

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HttpInputError(
                    "duplicate-json-key",
                    "The JSON object contains a duplicate key",
                    field=key,
                )
            result[key] = value
        return result

    def reject_non_finite(value: str) -> None:
        raise HttpInputError(
            "invalid-json-number", "JSON numbers must be finite", field=field
        )

    try:
        parsed = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_non_finite,
        )
    except HttpInputError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise HttpInputError("invalid-json", "The request body is not valid JSON", field=field) from error
    if not isinstance(parsed, dict):
        raise HttpInputError("invalid-json-shape", "The JSON body must be an object", field=field)
    _require_finite_numbers(parsed, field)
    return parsed


def _require_finite_numbers(value: Any, field: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise HttpInputError("invalid-json-number", "JSON numbers must be finite", field=field)
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if not finite:
            raise HttpInputError("invalid-json-number", "JSON numbers must be finite", field=field)
    if isinstance(value, dict):
        for key, nested in value.items():
            _require_finite_numbers(nested, str(key))
    elif isinstance(value, list):
        for nested in value:
            _require_finite_numbers(nested, field)


def require_exact_keys(
    value: Mapping[str, Any],
    required: Iterable[str],
    allowed: Iterable[str],
    *,
    field: str,
) -> None:
    """Require a JSON object to contain required keys and no unknown keys."""
    required_set = set(required)
    allowed_set = set(allowed)
    missing = required_set - set(value)
    if missing:
        name = sorted(missing)[0]
        raise HttpInputError(
            "missing-field", "A required field is missing", field=f"{field}.{name}"
        )
    unknown = set(value) - allowed_set
    if unknown:
        name = sorted(unknown)[0]
        raise HttpInputError(
            "unknown-field", "The JSON object contains an unknown field", field=f"{field}.{name}"
        )
