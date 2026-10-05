"""Transport-independent inputs and results for task application services."""

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from src.wrappers.TimeManagement import TimePoint


@dataclass(frozen=True)
class TaskView:
    """Complete, explicit parameters for one independent task-list query."""

    filters: tuple[str, ...] = ("All active task filter",)
    page: int = 1
    page_size: int = 5
    algorithm: str = "GTD Algorithm"
    heuristic: str = "Remaining Effort(1)"
    search: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgendaQuery:
    """Parameters used to calculate one agenda without changing a client view."""

    day: TimePoint = field(default_factory=TimePoint.today)
    heuristic: str = "Remaining Effort(1)"


@dataclass(frozen=True)
class OperationTarget:
    """An explicit operation target. Task identifiers are provisional and are not persisted by reads."""

    kind: Literal["task", "tasks", "event", "project"]
    id: str | None = None


@dataclass(frozen=True)
class OperationResult:
    """Typed outcome from one domain operation, independent of a UI protocol."""

    operation_type: str
    target: OperationTarget
    value: Any = None
    affected_ids: tuple[str, ...] = ()
    effects_state: Literal["none", "complete", "partial", "unknown"] = "complete"
    metadata: Mapping[str, Any] = field(default_factory=dict)
