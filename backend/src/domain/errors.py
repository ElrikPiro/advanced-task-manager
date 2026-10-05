"""Typed domain errors; adapters decide how to present them."""

from typing import Literal


EffectsState = Literal["none", "complete", "partial", "unknown"]


class DomainError(Exception):
    """Base class for expected errors raised by application services."""

    code = "domain-error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, str] | None = None,
        effects_state: EffectsState | None = "none",
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


class ResourceConflictError(DomainError):
    """A requested resource already exists in a conflicting form."""

    code = "resource-conflict"


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


class OperationResultUnavailableError(DomainError):
    """No retained result exists for an operation identifier."""

    code = "operation-result-unavailable"

    def __init__(self, operation_id: str):
        super().__init__(
            "No retained result is available for this operation",
            details={"operation_id": operation_id},
            effects_state="unknown",
        )


class OperationConflictError(DomainError):
    """An operation identifier was already admitted with another intent."""

    code = "operation-id-conflict"

    def __init__(self, operation_id: str):
        super().__init__(
            "This operation identifier was already used for different parameters",
            details={"operation_id": operation_id},
            effects_state="none",
        )


class OperationFailedError(DomainError):
    """A domain write failed; effects are reported without guessing a rollback."""

    code = "operation-failed"

    def __init__(
        self,
        message: str,
        *,
        effects_state: Literal["none", "partial", "unknown"] = "unknown",
        details: dict[str, str] | None = None,
    ):
        super().__init__(message, details=details, effects_state=effects_state)
        self.effects_state = effects_state
