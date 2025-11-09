from typing import TypeAlias
from dataclasses import dataclass

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


def stripDoc(docstring: str) -> str:
    """
    Strip the leading whitespace from the docstring.

    Args:
        docstring (str): The docstring
    Returns:
        str: The docstring without leading whitespace
    """
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
