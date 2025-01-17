from math import ceil
from .Interfaces.IScheduling import IScheduling
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskProvider import ITaskProvider
from .wrappers.TimeManagement import TimeAmount

class HeuristicScheduling(IScheduling):
    
    def __init__(self, pomodoroConstProvider : ITaskProvider):
        self.pomodoroConstProvider = pomodoroConstProvider

    def schedule(self, task: ITaskModel, param: str) -> None:
        
        d = task.calculateRemainingTime()
        p = float(self.pomodoroConstProvider.getTaskListAttribute("pomodoros_per_day"))
        r = task.getTotalCost().int_representation

        if param.replace(".", "").isnumeric():
            effortPerDay = float(param)
            severity = 1 / effortPerDay
            optimalDayTo = ceil((r * (p * severity + 1)) / p)
            task.setDue(task.getStart() + TimeAmount(f"{optimalDayTo}d"))
            task.setSeverity(severity)
        else:
            severity = max((d*p-r)/(p*r), 1)
            task.setSeverity(severity)
