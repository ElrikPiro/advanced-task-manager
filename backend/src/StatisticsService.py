import datetime

from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFileBroker import IFileBroker, FileRegistry
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .wrappers.TimeManagement import TimePoint, TimeAmount


class StatisticsService(IStatisticsService):

    def __init__(self, fileBroker: IFileBroker, workLoadAbleFilter: IFilter, remainingEffortHeuristic: IHeuristic, mainHeuristic: IHeuristic):
        self.workDone: dict = {datetime.date.today().isoformat(): 0.0}
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

    def doWork(self, date: datetime.date, work_units: TimeAmount, task: ITaskModel):
        work_units_pomodoros: float = work_units.as_pomodoros()
        self.workDone[date.isoformat()] = self.workDone.get(date.isoformat(), 0.0) + work_units_pomodoros
        self.workDone["log"] = self.workDone.get("log", [])
        self.workDone["log"].append({"timestamp": TimePoint.now().as_int(), "work_units": work_units_pomodoros, "task": task.getDescription()})
        self.workDone["log"] = [entry for entry in self.workDone["log"] if TimePoint.now().as_int() - entry["timestamp"] < 86400000]

        print(f"Work done on {TimePoint.now()}: {work_units} on {task.getDescription()}")
        self.fileBroker.writeFileContentJson(FileRegistry.STATISTICS_JSON, self.workDone)

    def getWorkDone(self, date: TimePoint) -> TimeAmount:
        work_done: str = f"{self.workDone.get(date.datetime_representation.date().isoformat(), 0.0)}p"
        return TimeAmount(work_done)

    def getWorkloadStats(self, taskList: list[ITaskModel]) -> list:
        filteredTasks = self.workLoadAbleFilter.filter(taskList)

        workload: TimeAmount = TimeAmount("0.0p")
        remainingEffort: TimeAmount = TimeAmount("0.0p")
        maxHeuristic = 0.0
        HeuristicName = self.mainHeuristic.__class__.__name__
        offender: str = None
        offenderMax: TimeAmount = TimeAmount("0.0p")

        for task in filteredTasks:
            taskRE = TimeAmount(f"{self.remainingEffortHeuristic.evaluate(task)}p")
            taskH = self.mainHeuristic.evaluate(task)
            taskWL = TimeAmount(f"{task.getTotalCost().as_pomodoros() / task.calculateRemainingTime().as_days()}p")

            workload += taskWL
            remainingEffort += taskRE if taskRE.as_pomodoros() > 0 else TimeAmount("0.0p")
            if taskH > maxHeuristic:
                maxHeuristic = taskH
            if offenderMax.as_pomodoros() < taskWL.as_pomodoros():
                offenderMax = taskWL
                offender = task.getDescription()

        retval = [workload, remainingEffort, maxHeuristic, HeuristicName, offender, offenderMax]
        return retval

    def getWorkDoneLog(self) -> list:
        return self.workDone["log"]
