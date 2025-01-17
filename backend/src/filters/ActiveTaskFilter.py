import datetime

from ..Interfaces.IFilter import IFilter
from ..Interfaces.ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimePoint

def filter(tasks : list[ITaskModel], invert : bool) -> list:
        retval = []

        for task in tasks:
            startTime = task.getStart()
            currentTime = TimePoint.now()
            status = task.getStatus()

            isTaskActived = (startTime.datetime_representation.timestamp() <= currentTime.datetime_representation.timestamp()) ^ invert

            # if the task start time is before the current time, it is an active task
            if isTaskActived and status == " ":
                retval.append(task)
            else:
                continue

        return retval

class ActiveTaskFilter(IFilter):

    def filter(self, tasks : list[ITaskModel]) -> list:
        return filter(tasks, False)
    
    def getDescription(self) -> str:
        return "Active tasks"
    
class InactiveTaskFilter(IFilter):

    def filter(self, tasks : list[ITaskModel]) -> list:
        return filter(tasks, True)
    
    def getDescription(self) -> str:
        return "Inactive tasks"
    
