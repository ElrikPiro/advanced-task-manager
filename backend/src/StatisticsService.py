import datetime

from src.Utils import WorkLogEntry, WorkloadStats

from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFileBroker import IFileBroker, FileRegistry
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .wrappers.TimeManagement import TimePoint, TimeAmount


class StatisticsService(IStatisticsService):

    def __init__(self, fileBroker: IFileBroker, workLoadAbleFilter: IFilter, remainingEffortHeuristic: IHeuristic, mainHeuristic: IHeuristic) -> None:
        self.workDone: dict[str, float | list[WorkLogEntry]] = {datetime.date.today().isoformat(): 0.0}
        self.fileBroker = fileBroker
        self.workLoadAbleFilter = workLoadAbleFilter
        self.remainingEffortHeuristic = remainingEffortHeuristic
        self.mainHeuristic = mainHeuristic

    def initialize(self) -> None:
        try:
            data = self.fileBroker.readStatisticsFileContentJson()
            self.workDone = data
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}")
            print("Initializing StatisticsService with empty data.")

    def doWork(self, date: datetime.date, work_units: TimeAmount, task: ITaskModel) -> None:
        work_units_pomodoros: float = work_units.as_pomodoros()
        current_work_done = self.workDone.get(date.isoformat(), 0.0)
        log_list = self.workDone.get("log", [])

        if not isinstance(current_work_done, float) or not isinstance(log_list, list):
            return
        
        # Update the date-based work done entry
        new_work_total = current_work_done + work_units_pomodoros
        
        new_log_entry = WorkLogEntry(
            timestamp=TimePoint.now().as_int(),
            work_units=work_units_pomodoros,
            task=task.getDescription()
        )

        log_list.append(new_log_entry)
        log_list = [entry for entry in log_list if TimePoint.now().as_int() - entry.timestamp < 86400000]
        
        self.workDone[date.isoformat()] = new_work_total
        self.workDone["log"] = log_list

        print(f"Work done on {TimePoint.now()}: {work_units} on {task.getDescription()}")
        self.fileBroker.writeFileContentJson(FileRegistry.STATISTICS_JSON, self.workDone)

    def getWorkDone(self, date: TimePoint) -> TimeAmount:
        work_done: str = f"{self.workDone.get(date.datetime_representation.date().isoformat(), 0.0)}p"
        return TimeAmount(work_done)

    def getWorkloadStats(self, taskList: list[ITaskModel]) -> WorkloadStats:
        filteredTasks = self.workLoadAbleFilter.filter(taskList)

        workload: TimeAmount = TimeAmount("0.0p")
        remainingEffort: TimeAmount = TimeAmount("0.0p")
        maxHeuristic = 0.0
        HeuristicName = self.mainHeuristic.__class__.__name__
        offender: str | None = None
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

        filtered_work_done: dict[str, float] = {
            key: value for key, value in self.workDone.items()
            if isinstance(value, float)
        }

        return WorkloadStats(
            workload=workload,
            remainingEffort=remainingEffort,
            maxHeuristic=maxHeuristic,
            HeuristicName=HeuristicName,
            offender=offender if isinstance(offender, str) else "None",
            offenderMax=offenderMax,
            workDone=filtered_work_done
        )

    def getWorkDoneLog(self) -> list[WorkLogEntry]:
        logList = self.workDone["log"]
        return logList if isinstance(logList, list) else []
