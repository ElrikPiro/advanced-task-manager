from typing import TypeAlias
from dataclasses import dataclass
import typing

from src.wrappers.TimeManagement import TimeAmount, TimePoint
from dataclasses import asdict

TaskJsonElementType = dict[str, str]
TaskJsonListType = list[TaskJsonElementType]
ProjectJsonElementType = dict[str, str]
ProjectJsonListType = list[ProjectJsonElementType]
TaskJsonType: TypeAlias = dict[str, TaskJsonListType | ProjectJsonListType]

FileContentString = str
FileContentJson = TaskJsonType  # StatisticsJsonType
FileContent: TypeAlias = FileContentJson | FileContentString


@dataclass
class FilterEntry:
    name: str
    description: str
    enabled: bool


FilterList: TypeAlias = list[FilterEntry]
FilterListDict: TypeAlias = dict[str, FilterList]


@dataclass
class TaskEntry:
    id: str
    description: str
    context: str
    start: str
    due: str
    severity: float
    status: str
    total_cost: float
    effort_invested: float
    heuristic_value: float


@dataclass
class ActiveFilterEntry:
    name: str
    index: int
    description: str


@dataclass
class TaskListContent:
    algorithm_name: str
    algorithm_desc: str
    sort_heuristic: str
    tasks: list[TaskEntry]
    total_tasks: int
    current_page: int
    total_pages: int
    active_filters: list[ActiveFilterEntry]
    interactive: bool


@dataclass
class TaskDiscoveryPolicies:
    context_missing_policy: str
    date_missing_policy: str
    default_context: str
    categories_prefixes: list[str]


@dataclass
class WorkLogEntry:
    timestamp: int
    work_units: float
    task: str
    
    @typing.no_type_check
    def __dict__(self) -> dict:
        return asdict(self)


@dataclass
class WorkloadStats:
    workload: TimeAmount
    remainingEffort: TimeAmount
    maxHeuristic: float
    HeuristicName: str
    offender: str
    offenderMax: TimeAmount
    workDone: dict[str, float]
    workDoneLog: list[WorkLogEntry]


StatisticsFileContentJson = dict[str, float | list[WorkLogEntry]]


@dataclass
class AgendaContent:
    date: TimePoint
    active_urgent_tasks: list[TaskEntry]
    planned_urgent_tasks: list[TaskEntry]
    planned_tasks_by_date: dict[str, list[TaskEntry]]
    other_tasks: list[TaskEntry]
    other_task_list_info: TaskListContent | None


@dataclass
class TaskHeuristicsInfo:
    name: str
    value: float
    comment: str


@dataclass
class ExtendedTaskInformation:
    heuristics: list[TaskHeuristicsInfo]
    metadata: str


@dataclass
class EventStatistics:
    event_name: str
    tasks_raising: int
    tasks_waiting: int
    is_orphaned: bool
    orphan_type: str  # "raised_only", "waited_only", or "none"


@dataclass
class EventsContent:
    total_events: int
    total_raising_tasks: int
    total_waiting_tasks: int
    orphaned_events_count: int
    event_statistics: list[EventStatistics]


@dataclass
class TaskInformation:
    task: TaskEntry
    extended: ExtendedTaskInformation | None


def stripDoc(docstring: str | None) -> str:
    """
    Strip the leading whitespace from the docstring.

    Args:
        docstring (str): The docstring
    Returns:
        str: The docstring without leading whitespace
    """
    if not isinstance(docstring, str):
        return ""
    
    sanitizedDocstring = docstring.strip()
    if not sanitizedDocstring:
        return sanitizedDocstring

    lines = docstring.splitlines()
    if len(lines) == 1:
        return sanitizedDocstring

    indent = len(docstring)
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))

    return lines[0].strip() + "\n" + "\n".join(line[indent:] for line in lines[1:])
