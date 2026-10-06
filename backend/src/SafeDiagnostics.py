"""Create bounded diagnostics that omit exception text and local values."""

import re


_MAX_EXCEPTION_CHAIN = 8
_MAX_TRACEBACK_FRAMES = 20
_MAX_LABEL_LENGTH = 80
_SAFE_LABEL = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_label(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    label = _SAFE_LABEL.sub("_", value)[:_MAX_LABEL_LENGTH]
    return label or fallback


def _exception_parent(error: BaseException) -> BaseException | None:
    cause = error.__cause__
    if cause is not None:
        return cause
    if not error.__suppress_context__:
        return error.__context__
    return None


def format_safe_exception_diagnostic(error: BaseException) -> str:
    """Return exception classes and source basenames without message contents.

    The result is intended for local service diagnostics. It never includes
    exception messages, arguments, source lines, function names, locals, or
    absolute paths, and it places strict bounds on exception and frame counts.
    """
    if not isinstance(error, BaseException):
        return "exception_chain=unknown; frames=none"

    exception_names: list[str] = []
    frame_labels: list[str] = []
    visited: set[int] = set()
    current: BaseException | None = error

    while current is not None and len(exception_names) < _MAX_EXCEPTION_CHAIN:
        if id(current) in visited:
            break
        visited.add(id(current))
        exception_names.append(_safe_label(type(current).__name__, "Exception"))

        traceback = current.__traceback__
        while traceback is not None and len(frame_labels) < _MAX_TRACEBACK_FRAMES:
            source_name = traceback.tb_frame.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
            source_name = _safe_label(source_name, "<unknown>")
            frame_labels.append(f"{source_name}:{traceback.tb_lineno}")
            traceback = traceback.tb_next

        current = _exception_parent(current)

    if current is not None and len(exception_names) >= _MAX_EXCEPTION_CHAIN:
        exception_names.append("...")

    exception_chain = ">".join(exception_names) or "unknown"
    frames = ",".join(frame_labels) or "none"
    return f"exception_chain={exception_chain}; frames={frames}"
