from math import ceil
from typing import List

from .wrappers.TimeManagement import TimeAmount
from .Interfaces.IScheduling import IScheduling
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskProvider import ITaskProvider


class HeuristicScheduling(IScheduling):

    def __init__(self, dedication: TimeAmount, task_provider: ITaskProvider):
        self.__dedication = dedication
        self.__task_provider = task_provider

    def schedule(self, task: ITaskModel, param: str) -> List[ITaskModel]:
        d = task.calculateRemainingTime().as_days()
        p = self.__dedication.as_pomodoros()
        r = task.getTotalCost().as_pomodoros()

        # Parse effort per day from parameter
        effort_per_day = self._parse_effort_per_day(param, d, p, r)
        
        if effort_per_day is not None:
            return self._schedule_with_effort_per_day(task, effort_per_day, p, r)
        else:
            # Auto-calculation fallback
            return self._schedule_auto(task, d, p, r)

    def _parse_effort_per_day(self, param: str, d: int, p: float, r: float) -> float | None:
        """Parse effort per day parameter. Returns None for auto-calculation."""
        if not param or param.lower() in ["", "auto"]:
            return None
            
        # Handle pure numeric input (backward compatibility)
        if param.replace(".", "").isnumeric():
            return float(param)
        
        # Handle time format inputs using TimeAmount
        try:
            # Try to parse as TimeAmount (supports h, m, p, d, w, s formats)
            time_amount = TimeAmount(param)
            return time_amount.as_pomodoros()
        except (ValueError, Exception):
            # If parsing fails, return None for auto-calculation
            return None

    def _schedule_with_effort_per_day(self, task: ITaskModel, effort_per_day: float, p: float, r: float) -> List[ITaskModel]:
        """Schedule task with specified effort per day, splitting if necessary."""
        severity = p / effort_per_day
        
        if severity >= 1.0:
            # Normal scheduling - no split needed
            return [self._apply_normal_scheduling(task, effort_per_day, p, r)]
        else:
            # Split task to achieve severity >= 1
            return self._split_task(task, effort_per_day, p, r)

    def _schedule_auto(self, task: ITaskModel, d: int, p: float, r: float) -> List[ITaskModel]:
        """Auto-calculate severity based on available time."""
        severity = max((d * p - r) / (p * r), 1.0)
        task.setSeverity(severity)
        return [task]

    def _apply_normal_scheduling(self, task: ITaskModel, effort_per_day: float, p: float, r: float) -> ITaskModel:
        """Apply normal scheduling logic to a single task."""
        severity = p / effort_per_day
        optimal_days = ceil((r * (p * severity + 1)) / p)
        task.setDue(task.getStart() + TimeAmount(f"{optimal_days}d"))
        task.setSeverity(severity)
        return task

    def _split_task(self, task: ITaskModel, effort_per_day: float, p: float, r: float) -> List[ITaskModel]:
        """Split task into multiple parts when severity would be < 1."""
        severity = p / effort_per_day
        split_count = ceil(1.0 / severity)
        optimal_effort_per_day = 1.0  # Target severity = 1
        effort_per_split = r / split_count
        
        split_tasks: List[ITaskModel] = []
        original_description = task.getDescription()
        
        for i in range(split_count):
            split_task: ITaskModel
            if i == 0:
                # Modify original task
                split_task = task
            else:
                # Create new task using TaskProvider
                split_task = self.__task_provider.createDefaultTask(f"{original_description} {i+1}/{split_count}")
                self._copy_task_properties(task, split_task)
            
            # Apply sequential naming to all tasks (including original)
            split_task.setDescription(f"{original_description} {i+1}/{split_count}")
            split_task.setTotalCost(TimeAmount(f"{effort_per_split}p"))
            
            # Apply optimal scheduling with severity = 1
            self._apply_normal_scheduling(split_task, optimal_effort_per_day, p, effort_per_split)
            split_tasks.append(split_task)
        
        return split_tasks

    def _copy_task_properties(self, source: ITaskModel, target: ITaskModel) -> None:
        """Copy all relevant properties from source to target task."""
        target.setContext(source.getContext())
        target.setStart(source.getStart())
        target.setDue(source.getDue())
        target.setSeverity(source.getSeverity())
        target.setTotalCost(source.getTotalCost())
        target.setInvestedEffort(source.getInvestedEffort())
        target.setStatus(source.getStatus())
        target.setCalm(source.getCalm())
        # Note: Project property doesn't have setter in interface, might be read-only
