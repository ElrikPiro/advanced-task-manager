from .Interfaces.IFilter import IFilter
from .Interfaces.ITaskModel import ITaskModel

class ContextPrefixTaskFilter(IFilter):

    def __init__(self, prefilter : IFilter, prefix: str):
        self.prefix = prefix
        self.prefilter = prefilter
        pass

    def filter(self, tasks : list[ITaskModel]) -> list:
        preTasks = self.prefilter.filter(tasks) if self.prefilter != None else tasks
        retval = []

        for task in preTasks:
            if task.getContext().startswith(self.prefix):
                retval.append(task)
            else:
                continue

        return retval