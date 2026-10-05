import hashlib


class InvalidTaskIdentityError(ValueError):
    """Raised when a stored task ID is not a non-empty opaque string."""


class AmbiguousTaskIdentityError(LookupError):
    """Raised when an ID resolves to more than one stored task."""


class MissingTaskIdentityError(LookupError):
    """Raised when an ID does not resolve to a stored task."""


def fallback_task_id(description: str, path: str, position: int) -> str:
    """Return the legacy MD5 identity for a task at its current location."""
    if not isinstance(description, str):
        raise TypeError("Task description must be a string to derive its identity")
    if not isinstance(path, str):
        raise TypeError("Configured task file path must be a string")
    if not isinstance(position, int):
        raise TypeError("Task position must be an integer")
    value = f"{description}{path}{position}"
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def validate_task_id(value: object) -> str:
    """Validate an opaque task ID without changing its value."""
    if not isinstance(value, str) or value == "" or value.isspace():
        raise InvalidTaskIdentityError("Task ID must be a non-empty string")
    return value
