import datetime

from .Interfaces.IFilter import IFilter
from .Interfaces.ITaskModel import ITaskModel

class ActiveTaskFilter(IFilter):

    def filter(self, tasks : list[ITaskModel]) -> list:
        return [task for task in tasks if datetime.datetime.fromtimestamp(task.getStart() / 1000) <= datetime.datetime.now()]