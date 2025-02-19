from typing import List
from ..Interfaces.ITaskModel import ITaskModel
from ..Interfaces.IFilter import IFilter


class WorkloadAbleFilter(IFilter):

    def __init__(self, activeFilter: IFilter):
        self.activeFilter = activeFilter

    def filter(self, tasks: List[ITaskModel]) -> List[ITaskModel]:
        activeTasks = self.activeFilter.filter(tasks)
        workloadAbleTasks = []
        for task in activeTasks:
            if task.calculateRemainingTime().as_days() >= 1.0:
                workloadAbleTasks.append(task)
        return workloadAbleTasks

    def getDescription(self) -> str:
        return "Non-urgent tasks"
