import datetime
import math
from copy import deepcopy
from typing import Any

from src.Utils import WorkLogEntry, WorkloadStats, EventsContent, EventStatistics

from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFileBroker import IFileBroker, FileRegistry
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .wrappers.TimeManagement import TimePoint, TimeAmount


class StatisticsUpdateError(ValueError):
    """A statistics update was rejected before any file could be published."""

    effects_state = "none"


class ConfirmedStatisticsRefreshError(RuntimeError):
    """The file update was confirmed but its returned document was unusable."""

    effects_state = "unknown"


class StatisticsService(IStatisticsService):

    def __init__(self, fileBroker: IFileBroker, workLoadAbleFilter: IFilter, remainingEffortHeuristic: IHeuristic, mainHeuristic: IHeuristic) -> None:
        self.workDone: dict[str, float | list[WorkLogEntry]] = {datetime.date.today().isoformat(): 0.0}
        self.fileBroker = fileBroker
        self.workLoadAbleFilter = workLoadAbleFilter
        self.remainingEffortHeuristic = remainingEffortHeuristic
        self.mainHeuristic = mainHeuristic

    def initialize(self) -> None:
        data = self.fileBroker.readStatisticsFileContentJson()
        if not isinstance(data, dict):
            raise TypeError("Statistics document must be an object")
        self.workDone = deepcopy(data)

    def doWork(self, date: datetime.date, work_units: TimeAmount, task: ITaskModel) -> None:
        try:
            work_units_pomodoros: float = work_units.as_pomodoros()
        except Exception as error:
            raise StatisticsUpdateError("Work units could not be converted") from error
        if not math.isfinite(work_units_pomodoros):
            raise StatisticsUpdateError("Work units must be a finite number")

        try:
            timestamp = TimePoint.now().as_int()
            task_description = task.getDescription()
        except Exception as error:
            raise StatisticsUpdateError("Work log entry could not be prepared") from error
        day_key = date.isoformat()

        def prepare(current: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(current, dict):
                raise TypeError("Statistics document must be an object")

            updated = deepcopy(current)
            current_total = updated.get(day_key, 0.0)
            if isinstance(current_total, bool) or not isinstance(current_total, (int, float)):
                raise TypeError(f"Statistics value for {day_key} must be numeric")
            if not math.isfinite(float(current_total)):
                raise ValueError(f"Statistics value for {day_key} must be finite")

            log_entries = updated.get("log", [])
            if not isinstance(log_entries, list):
                raise TypeError("Statistics log must be a list")

            retained_entries: list[dict[str, Any]] = []
            for entry in log_entries:
                if isinstance(entry, WorkLogEntry):
                    entry = entry.__dict__()
                if not isinstance(entry, dict):
                    raise TypeError("Every statistics log entry must be an object")
                if "timestamp" not in entry or "work_units" not in entry or not isinstance(entry.get("task"), str):
                    raise ValueError("Statistics log entry is missing required fields")
                if isinstance(entry["timestamp"], bool) or not isinstance(entry["timestamp"], int):
                    raise TypeError("Statistics log timestamp must be an integer")
                entry_timestamp = entry["timestamp"]
                if isinstance(entry["work_units"], bool) or not isinstance(entry["work_units"], (int, float)):
                    raise TypeError("Statistics log work units must be numeric")
                entry_units = float(entry["work_units"])
                if not math.isfinite(entry_units):
                    raise ValueError("Statistics log work units must be finite")
                if timestamp - entry_timestamp < 86400000:
                    retained_entries.append(deepcopy(entry))

            updated[day_key] = float(current_total) + work_units_pomodoros
            updated["log"] = retained_entries + [{
                "timestamp": timestamp,
                "work_units": work_units_pomodoros,
                "task": task_description,
            }]
            return updated

        try:
            committed = self.fileBroker.updateFileContentJson(FileRegistry.STATISTICS_JSON, prepare)
        except Exception as error:
            if getattr(error, "effects_state", None) in ("none", "unknown"):
                raise
            raise StatisticsUpdateError("Statistics update could not be prepared") from error
        if not isinstance(committed, dict):
            raise ConfirmedStatisticsRefreshError("Statistics store returned an invalid confirmed document")
        committed_work_done = deepcopy(committed)
        try:
            committed_log = committed_work_done.get("log", [])
            committed_work_done["log"] = self.__as_work_log_entries(committed_log)
        except Exception as error:
            raise ConfirmedStatisticsRefreshError("Statistics cache could not be refreshed from confirmed data") from error
        self.workDone = committed_work_done
        print(f"Work done on {TimePoint.now()}: {work_units} on {task_description}")

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

        filtered_work_done: dict[str, float] = {}
        for key, value in self.workDone.items():
            if key == "log":
                continue
            try:
                datetime.date.fromisoformat(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"Statistics value for {key} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"Statistics value for {key} must be finite")
            filtered_work_done[key] = float(value)

        log_list = self.__as_work_log_entries(self.workDone.get("log", []))

        return WorkloadStats(
            workload=workload,
            remainingEffort=remainingEffort,
            maxHeuristic=maxHeuristic,
            HeuristicName=HeuristicName,
            offender=offender if isinstance(offender, str) else "None",
            offenderMax=offenderMax,
            workDone=filtered_work_done,
            workDoneLog=log_list
        )

    def getWorkDoneLog(self) -> list[WorkLogEntry]:
        logList = self.workDone.get("log", [])
        return self.__as_work_log_entries(logList)

    @staticmethod
    def __as_work_log_entries(value: Any) -> list[WorkLogEntry]:
        if not isinstance(value, list):
            raise TypeError("Statistics log must be a list")
        entries: list[WorkLogEntry] = []
        for item in value:
            if isinstance(item, WorkLogEntry):
                entries.append(item)
                continue
            if not isinstance(item, dict):
                raise TypeError("Every statistics log entry must be an object")
            try:
                timestamp = item["timestamp"]
                work_units = item["work_units"]
                task = item["task"]
                if isinstance(timestamp, bool) or not isinstance(timestamp, int):
                    raise TypeError("Statistics log timestamp must be an integer")
                if isinstance(work_units, bool) or not isinstance(work_units, (int, float)):
                    raise TypeError("Statistics log work units must be numeric")
                if not math.isfinite(float(work_units)):
                    raise ValueError("Statistics log work units must be finite")
                if not isinstance(task, str):
                    raise TypeError("Statistics log task must be a string")
                entries.append(WorkLogEntry(
                    timestamp=timestamp,
                    work_units=float(work_units),
                    task=task,
                ))
            except (KeyError, TypeError, ValueError, OverflowError) as error:
                raise ValueError("Statistics log entry is invalid") from error
        return entries

    def getEventStatistics(self, taskList: list[ITaskModel]) -> EventsContent:
        """
        Analyze event statistics from all tasks to identify raised/waited events and orphans.
        
        Args:
            taskList: List of tasks to analyze for event statistics
            
        Returns:
            EventsContent: Structured data containing event statistics
        """
        # Collect all events being raised and waited for
        events_raised: dict[str, int] = {}
        events_waited: dict[str, int] = {}
        
        total_raising_tasks = 0
        total_waiting_tasks = 0
        
        for task in taskList:
            # Check raised events
            raised_event = task.getEventRaised()
            if raised_event:
                events_raised[raised_event] = events_raised.get(raised_event, 0) + 1
                total_raising_tasks += 1
            
            # Check waited events
            waited_event = task.getEventWaited()
            if waited_event:
                events_waited[waited_event] = events_waited.get(waited_event, 0) + 1
                total_waiting_tasks += 1
        
        # Get all unique event names
        all_events = set(events_raised.keys()) | set(events_waited.keys())
        
        # Create statistics for each event
        event_statistics: list[EventStatistics] = []
        orphaned_events_count = 0
        
        for event_name in sorted(all_events):
            tasks_raising = events_raised.get(event_name, 0)
            tasks_waiting = events_waited.get(event_name, 0)
            
            # Determine if orphaned and type
            is_orphaned = False
            orphan_type = "none"
            
            if tasks_raising > 0 and tasks_waiting == 0:
                is_orphaned = True
                orphan_type = "raised_only"
                orphaned_events_count += 1
            elif tasks_waiting > 0 and tasks_raising == 0:
                is_orphaned = True
                orphan_type = "waited_only"
                orphaned_events_count += 1
            
            event_statistics.append(EventStatistics(
                event_name=event_name,
                tasks_raising=tasks_raising,
                tasks_waiting=tasks_waiting,
                is_orphaned=is_orphaned,
                orphan_type=orphan_type
            ))
        
        return EventsContent(
            total_events=len(all_events),
            total_raising_tasks=total_raising_tasks,
            total_waiting_tasks=total_waiting_tasks,
            orphaned_events_count=orphaned_events_count,
            event_statistics=event_statistics
        )
