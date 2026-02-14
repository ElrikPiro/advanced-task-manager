from datetime import datetime
from typing import List, Tuple

from src.Interfaces.IFilter import IFilter
from src.Interfaces.IHeuristic import IHeuristic
from src.Interfaces.IStatisticsService import IStatisticsService
from src.wrappers.TimeManagement import TimePoint
from src.Interfaces.ITaskModel import ITaskModel
from src.algorithms.Interfaces.IAlgorithm import IAlgorithm


class GtdAlgorithm(IAlgorithm):
    """
    GTD Algorithm implementation.
    This algorithm filters tasks based on their urgency and heuristic values.

    It applies a series of filters to determine which tasks should be processed.
    The algorithm is designed to work with a list of tasks and apply various heuristics
    to prioritize them.

    The algorithm consists of the following steps:
    1. Filter tasks with due dates before the current time (urgent tasks).
    2. Filter tasks based on ordered categories.
    3. Filter tasks based on heuristic values and thresholds.
    4. Filter tasks based on calmness.
    5. Apply a default heuristic if no other tasks are found.
    6. Return the filtered list of tasks.
    """

    def __init__(self, orderedCategories: list[tuple[str, IFilter, bool]], orderedHeuristics: list[tuple[IHeuristic, float]], defaultHeuristic: Tuple[IHeuristic, float], statisticService: IStatisticsService, calmHeuristic: IHeuristic) -> None:
        self.orderedCategories = orderedCategories
        self.orderedHeuristics = orderedHeuristics
        self.defaultHeuristic = defaultHeuristic
        self.statisticService = statisticService
        self.calmHeuristic = calmHeuristic
        self.baseDescription = "GTD Task Algorithm"
        self.description = self.baseDescription
        self.category = "all"
    pass

    def apply(self, taskList: List[ITaskModel]) -> List[ITaskModel]:
        """
        Execute the GTD algorithm with the given parameters.

        Args:
            taskList (list): The list of tasks to be processed by the algorithm.

        Returns:
            list: The list of tasks after applying the algorithm.
        """
        self.description = self.baseDescription
        self.category = "all"

        # get all task with due date before now
        nonCalm = self._filterCalmTasks(taskList)
        retval = self._filterUrgents(nonCalm)
        retval = self._filterOrderedCategories(retval)

        if len(retval) > 0:
            self.description = f"{self.baseDescription} \n    - Urgent tasks ({self.category})"
            return retval

        # get all task with heuristic value above threshold and NOT calm
        for heuristic, threshold in self.orderedHeuristics:
            retval = self._filterByHeuristic(heuristic, threshold, nonCalm)
            retval = self._filterOrderedCategories(retval)
            if len(retval) > 0:
                self.description = f"{self.baseDescription} \n    - {heuristic.__class__.__name__} >= {threshold} ({self.category})"
                return retval

        # get default working model
        isoformatDate = datetime.now().date().isoformat()
        workStats = self.statisticService.getWorkloadStats(nonCalm)
        if workStats.workDone.get(isoformatDate, 0.0) < workStats.workload.as_pomodoros():
            heuristic, threshold = self.defaultHeuristic
            retval = self._filterByHeuristic(heuristic, threshold, nonCalm)
            self.description = f"{self.baseDescription} \n    - {heuristic.__class__.__name__} >= {threshold} ({self.category})"
        else:
            calmTasks = self._filterCalmTasks(taskList, notCalm=False)
            sortedTasks = self.calmHeuristic.sort(calmTasks)
            retval = [task for task, _ in sortedTasks]
            self.description = f"{self.baseDescription} \n    - {self.calmHeuristic.__class__.__name__}"
        return retval

    def getDescription(self) -> str:
        return self.description

    def _filterUrgents(self, tasks: List[ITaskModel]) -> list[ITaskModel]:
        retval: list[ITaskModel] = []
        for task in tasks:
            if task.getDue().as_int() < TimePoint.now().as_int():
                retval.append(task)
        return retval

    def _filterOrderedCategories(self, tasks: list[ITaskModel]) -> list[ITaskModel]:
        filteredTasks = []
        for description, category, _ in self.orderedCategories:
            filteredTasks = category.filter(tasks)
            if len(filteredTasks) == 0:
                continue
            else:
                self.category = description
                break
        return filteredTasks

    def _filterByHeuristic(self, heuristic: IHeuristic, threshold: float, tasks: list[ITaskModel]) -> list[ITaskModel]:
        retval: list[ITaskModel] = []
        for task in tasks:
            if heuristic.evaluate(task) >= threshold:
                retval.append(task)
        return retval

    def _filterCalmTasks(self, tasks: list[ITaskModel], notCalm: bool = True) -> list[ITaskModel]:
        retval: list[ITaskModel] = []
        for task in tasks:
            if task.getCalm() ^ notCalm:
                retval.append(task)
        return retval
