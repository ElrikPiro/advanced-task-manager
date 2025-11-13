from typing import List

from ..wrappers.TimeManagement import TimePoint

from ..Interfaces.IFilter import IFilter
from ..Interfaces.ITaskModel import ITaskModel


def filter(tasks: list[ITaskModel], invert: bool) -> List[ITaskModel]:
    retval: List[ITaskModel] = []

    for task in tasks:
        startTime = task.getStart().datetime_representation
        currentTime = TimePoint.now().datetime_representation
        status = task.getStatus()

        isTaskActived = (startTime.timestamp() <= currentTime.timestamp()) ^ invert

        # if the task start time is before the current time, it is an active task
        if isTaskActived and status == " ":
            retval.append(task)
        else:
            continue

    return retval


class ActiveTaskFilter(IFilter):

    def filter(self, tasks: list[ITaskModel]) -> List[ITaskModel]:
        return filter(tasks, False)

    def getDescription(self) -> str:
        return "Active tasks"


class InactiveTaskFilter(IFilter):

    def filter(self, tasks: list[ITaskModel]) -> List[ITaskModel]:
        return filter(tasks, True)

    def getDescription(self) -> str:
        return "Inactive tasks"
