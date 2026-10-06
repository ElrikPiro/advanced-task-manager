from typing import List

from ..wrappers.TimeManagement import TimePoint

from ..Interfaces.IFilter import IFilter
from ..Interfaces.ITaskModel import ITaskModel


def filter(
    tasks: list[ITaskModel],
    invert: bool,
    now: TimePoint | None = None,
) -> List[ITaskModel]:
    retval: List[ITaskModel] = []
    current_time = now or TimePoint.now()

    for task in tasks:
        startTime = task.getStart().datetime_representation
        status = task.getStatus()

        isTaskActived = (startTime.timestamp() <= current_time.datetime_representation.timestamp()) ^ invert

        # if the task start time is before the current time, it is an active task
        if isTaskActived and status == " ":
            retval.append(task)
        else:
            continue

    return retval


class ActiveTaskFilter(IFilter):

    def filter(self, tasks: list[ITaskModel]) -> List[ITaskModel]:
        return filter(tasks, False)

    def filter_at(self, tasks: list[ITaskModel], now: TimePoint) -> List[ITaskModel]:
        return filter(tasks, False, now)

    def getDescription(self) -> str:
        return "Active tasks"


class InactiveTaskFilter(IFilter):

    def filter(self, tasks: list[ITaskModel]) -> List[ITaskModel]:
        return filter(tasks, True)

    def filter_at(self, tasks: list[ITaskModel], now: TimePoint) -> List[ITaskModel]:
        return filter(tasks, True, now)

    def getDescription(self) -> str:
        return "Inactive tasks"
