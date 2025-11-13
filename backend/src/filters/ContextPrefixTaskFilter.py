from typing import List
from ..Interfaces.IFilter import IFilter
from ..Interfaces.ITaskModel import ITaskModel


class ContextPrefixTaskFilter(IFilter):

    def __init__(self, prefilter: IFilter | None, prefix: str) -> None:
        self.prefix = prefix
        self.prefilter = prefilter
        pass

    def filter(self, tasks: list[ITaskModel]) -> List[ITaskModel]:
        preTasks = self.prefilter.filter(tasks) if isinstance(self.prefilter, IFilter) else tasks
        retval: List[ITaskModel] = []

        for task in preTasks:
            if task.getContext().startswith(self.prefix):
                retval.append(task)
            else:
                continue

        return retval

    def getDescription(self) -> str:
        return "Tasks with context starting with " + self.prefix
