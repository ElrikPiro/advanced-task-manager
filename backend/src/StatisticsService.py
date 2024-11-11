import datetime

from .Interfaces.ITaskModel import ITaskModel

from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFileBroker import IFileBroker, FileRegistry
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic

class StatisticsService(IStatisticsService):

    def __init__(self, fileBroker : IFileBroker, workLoadAbleFilter : IFilter, remainingEffortHeuristic : IHeuristic, mainHeuristic : IHeuristic):
        self.workDone : dict[str, float] = {datetime.date.today().isoformat() : 0.0}
        self.fileBroker = fileBroker
        self.workLoadAbleFilter = workLoadAbleFilter
        self.remainingEffortHeuristic = remainingEffortHeuristic
        self.mainHeuristic = mainHeuristic

    def initialize(self):
        try:
            data = self.fileBroker.readFileContentJson(FileRegistry.STATISTICS_JSON)
            self.workDone = data
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}")
            print("Initializing StatisticsService with empty data.")

    def doWork(self, date : datetime.date, work_units : float):
        self.workDone[date.isoformat()] = self.workDone.get(date.isoformat(), 0.0) + work_units
        # Save to file
        self.fileBroker.writeFileContentJson(FileRegistry.STATISTICS_JSON, self.workDone)

    def getWorkDone(self, date : datetime.date) -> float:
        return self.workDone.get(date.isoformat(), 0.0)
    
    def _getWorkload(self, filteredTasks : list[ITaskModel]) -> float:
        workload = 0.0
        for task in filteredTasks:
            workload += task.getTotalCost() / task.calculateRemainingTime()

        return workload

    def getWorkloadStats(self, taskList : list[ITaskModel]) -> list:
        filteredTasks = self.workLoadAbleFilter.filter(taskList)

        workload = 0.9
        remainingEffort = 0.0
        maxHeuristic = 0.0
        HeuristicName = self.mainHeuristic.__class__.__name__
        offender : str = None
        offenderMax : float = 0.0


        for task in filteredTasks:
            taskRE = self.remainingEffortHeuristic.evaluate(task)
            taskH = self.mainHeuristic.evaluate(task)
            taskWL = task.getTotalCost() / task.calculateRemainingTime()

            workload += taskWL
            remainingEffort += taskRE if taskRE > 0 else 0
            if taskH > maxHeuristic:
                maxHeuristic = taskH
            if offenderMax < taskWL:
                offenderMax = taskWL
                offender = task.getDescription()
        
        retval = [workload, remainingEffort, maxHeuristic, HeuristicName, offender, offenderMax]
        return retval