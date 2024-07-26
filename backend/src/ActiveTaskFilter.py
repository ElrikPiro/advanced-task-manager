import datetime

from .Interfaces.IFilter import IFilter
from .Interfaces.ITaskModel import ITaskModel

def filter(tasks : list[ITaskModel], invert : bool) -> list:
        retval = []

        for task in tasks:
            startTime = datetime.datetime.fromtimestamp(task.getStart() / 1000)
            currentTime = datetime.datetime.now()

            # if the task start time is before the current time, it is an active task
            if (startTime.timestamp() <= currentTime.timestamp()) ^ invert:
                retval.append(task)
            else:
                continue

        return retval

class ActiveTaskFilter(IFilter):

    def filter(self, tasks : list[ITaskModel]) -> list:
        return filter(tasks, False)
    
class InactiveTaskFilter(IFilter):

    def filter(self, tasks : list[ITaskModel]) -> list:
        return filter(tasks, True)