"""Typed domain errors; adapters decide how to present them."""


class DomainError(Exception):
    """Base class for expected errors raised by application services."""

    code = "domain-error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, str] | None = None,
        effects_state: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.effects_state = effects_state


class ValidationError(DomainError):
    """The supplied view, changes, target, or operation parameters are invalid."""

    code = "invalid-input"


class ResourceNotFoundError(DomainError):
    """A requested task or resource does not exist."""

    code = "not-found"


class ResourceReadError(DomainError):
    """The provider could not read the requested domain data."""

    code = "resource-read-failed"


class InvalidResourceDataError(DomainError):
    """Stored task data declares an invalid identity or shape."""

    code = "invalid-resource-data"


class DomainCalculationError(DomainError):
    """A domain view could not be calculated from the available data."""

    code = "calculation-failed"


class AmbiguousResourceError(DomainError):
    """More than one current task matches the requested identity."""

    code = "ambiguous-resource"


class UnsupportedOperationError(DomainError):
    """The operation type is not supported by this application service."""

    code = "unsupported-operation"


class OperationFailedError(DomainError):
    """A domain write failed; effects are reported without guessing a rollback."""

    code = "operation-failed"

    def __init__(
        self,
        message: str,
        *,
        effects_state: str = "unknown",
        details: dict[str, str] | None = None,
    ):
        super().__init__(message, details=details, effects_state=effects_state)
        self.effects_state = effects_state
