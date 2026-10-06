import copy
import datetime
from typing import List, Tuple

from src.Utils import EventsContent

from .Utils import ActiveFilterEntry, AgendaContent, ExtendedTaskInformation, FilterListDict, FilterEntry, TaskEntry, TaskHeuristicsInfo, TaskInformation, TaskListContent, WorkloadStats

from .wrappers.TimeManagement import TimeAmount, TimePoint

from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskListManager import ITaskListManager
from .algorithms.Interfaces.IAlgorithm import IAlgorithm
from .domain.models import TaskView
from .algorithms.EdfAlgorithm import EdfAlgorithm
from .algorithms.ShortestJobAlgorithm import ShortestJobAlgorithm
from .filters.ActiveTaskFilter import ActiveTaskFilter, InactiveTaskFilter
from .heuristics.CfdHeuristic import CfdHeuristic
from .heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from .heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from .heuristics.SlackHeuristic import SlackHeuristic
from .heuristics.StartTimeHeuristic import StartTimeHeuristic
from .heuristics.WorkloadHeuristic import WorkloadHeuristic
from .taskmodels.ObsidianTaskModel import ObsidianTaskModel
from .taskmodels.TaskModel import TaskModel


_BATCHABLE_FILTER_TYPES = (ActiveTaskFilter, InactiveTaskFilter)
_PURE_BUILTIN_HEURISTIC_TYPES = (
    CfdHeuristic,
    DaysToThresholdHeuristic,
    RemainingEffortHeuristic,
    SlackHeuristic,
    StartTimeHeuristic,
    WorkloadHeuristic,
)
_PURE_BUILTIN_ALGORITHM_TYPES = (EdfAlgorithm, ShortestJobAlgorithm)


class TelegramTaskListManager(ITaskListManager):

    def __init__(self, taskModelList: List[ITaskModel], algorithms: List[Tuple[str, IAlgorithm]], heuristics: List[Tuple[str, IHeuristic]], filters: List[Tuple[str, IFilter, bool]], statistics_service: IStatisticsService, tasksPerPage: int = 5):

        self.__taskModelList = taskModelList

        self.__selectedTask = None

        self.__heuristicList = heuristics
        self.__selectedHeuristic = heuristics[0] if len(heuristics) > 0 else None

        self.__filterList = filters

        self.__algorithmList = algorithms
        self.__selectedAlgorithm = algorithms[0] if len(algorithms) > 0 else None

        self.__statistics_service = statistics_service
        self.__search_terms: tuple[str, ...] = ()
        self.__last_sorted_scores: dict[int, float] | None = None
        self.__last_scored_population: List[ITaskModel] | None = None

        self.reset_pagination(tasksPerPage)

    def raiseEvent(self, event: str) -> list[ITaskModel]:
        def awaits_event(task: ITaskModel) -> bool:
            waited = task.getEventWaited()
            if not isinstance(waited, str):
                return False
            else:
                return waited == event

        filtered = list(filter(awaits_event, self.__taskModelList))
        for task in filtered:
            task.setEventWaited(None)
            task.setStart(TimePoint.now())

        return filtered
            
    def getEventStatistics(self) -> EventsContent:
        return self.__statistics_service.getEventStatistics(self.__taskModelList)

    @property
    def filtered_task_list(self) -> List[ITaskModel]:

        newTaskList: List[ITaskModel] = []
        self.__last_sorted_scores = None
        self.__last_scored_population = None
        query_now = TimePoint.now()

        if self.__search_terms:
            search_terms = tuple(term.casefold() for term in self.__search_terms)
            # Q-011 search is its own view over every non-completed task. It
            # deliberately ignores category/activity filters, event waits and
            # the list's ordering strategies.
            return [
                task
                for task in self.__taskModelList
                if task.getStatus() != "x" and any(
                    term in task.getDescription().casefold() for term in search_terms
                )
            ]

        source_tasks = self.__taskModelList

        active_filters = [filterr for filterr in self.__filterList if filterr[2]]
        if self.__filterList and not active_filters:
            # A configured filter catalog with no selection is the empty union.
            return []
        batch_matches = (
            self.__batch_builtin_filter_matches(source_tasks, active_filters, query_now)
            if self.__filterList
            else None
        )
        if batch_matches is not None:
            newTaskList = batch_matches
        elif self.__filterList:
            # Custom filters retain their original per-task call ordering and
            # singleton input, since extensions may be stateful.
            for task in source_tasks:
                for filterr in active_filters:
                    matches = filterr[1].filter([task])
                    if filterr[2] and matches and not isinstance(task.getEventWaited(), str):
                        newTaskList.append(task)
                        break
        else:
            for task in source_tasks:
                if task.getStatus() != "x" and not isinstance(task.getEventWaited(), str):
                    newTaskList.append(task)

        if isinstance(self.__selectedHeuristic, tuple):
            heuristic: IHeuristic = self.__selectedHeuristic[1]
            sortedTaskList: List[Tuple[ITaskModel, float]] = heuristic.sort(newTaskList)
            if self.__can_reuse_sorted_scores(heuristic):
                self.__last_sorted_scores = {
                    id(task): score for task, score in sortedTaskList
                }
            newTaskList = [task for task, _ in sortedTaskList]

        if isinstance(self.__selectedAlgorithm, tuple):
            algorithm: IAlgorithm = self.__selectedAlgorithm[1]
            if not self.__can_reuse_sorted_scores(
                self.__selectedHeuristic[1]
                if isinstance(self.__selectedHeuristic, tuple)
                else None,
                algorithm,
            ):
                self.__last_sorted_scores = None
            newTaskList = algorithm.apply(newTaskList)

        if self.__last_sorted_scores is not None:
            self.__last_scored_population = newTaskList

        return newTaskList

    @staticmethod
    def __batch_builtin_filter_matches(
        source_tasks: List[ITaskModel],
        active_filters: List[Tuple[str, IFilter, bool]],
        query_now: TimePoint,
    ) -> List[ITaskModel] | None:
        """Batch only stateless built-in filters; custom filters keep legacy calls."""
        if not active_filters or any(
            type(filter_entry[1]) not in _BATCHABLE_FILTER_TYPES
            for filter_entry in active_filters
        ):
            return None
        if not all(type(task) in (TaskModel, ObsidianTaskModel) for task in source_tasks):
            return None

        matching_object_ids: set[int] = set()
        for _, filterr, _ in active_filters:
            filter_at = getattr(type(filterr), "filter_at")
            matching_object_ids.update(
                id(task) for task in filter_at(filterr, source_tasks, query_now)
            )
        return [
            task
            for task in source_tasks
            if id(task) in matching_object_ids and not isinstance(
                task.getEventWaited(), str
            )
        ]

    def __can_reuse_sorted_scores(
        self,
        heuristic: IHeuristic | None,
        algorithm: IAlgorithm | None = None,
    ) -> bool:
        if heuristic is None or type(heuristic) not in _PURE_BUILTIN_HEURISTIC_TYPES:
            return False
        if not all(
            type(task) in (TaskModel, ObsidianTaskModel)
            for task in self.__taskModelList
        ):
            return False
        selected_algorithm = algorithm
        if selected_algorithm is None and isinstance(self.__selectedAlgorithm, tuple):
            selected_algorithm = self.__selectedAlgorithm[1]
        return selected_algorithm is None or type(selected_algorithm) in _PURE_BUILTIN_ALGORITHM_TYPES

    @property
    def selected_task(self) -> ITaskModel | None:
        return self.__selectedTask

    @selected_task.setter
    def selected_task(self, task: ITaskModel | None) -> None:
        self.__selectedTask = task  # type: ignore

    def reset_pagination(self, tasksPerPage: int = 5) -> None:
        self.__taskListPage = 0
        self.__tasksPerPage = tasksPerPage

    def next_page(self) -> None:
        self.__taskListPage += 1

    def prior_page(self) -> None:
        if self.__taskListPage > 0:
            self.__taskListPage -= 1

    def select_task(self, message: str) -> None:
        task_list = self.filtered_task_list
        taskId = int(message.split("_")[1]) - 1
        offset = self.__taskListPage * self.__tasksPerPage
        if 0 <= taskId < len(task_list):
            self.__selectedTask = task_list[taskId + offset]  # type: ignore
        else:
            self.__selectedTask = None

    def clear_selected_task(self) -> None:
        self.__selectedTask = None

    def search_tasks(self, searchTerms: List[str]) -> "ITaskListManager":
        taskListSearched: list[ITaskModel] = []
        for task in self.__taskModelList:
            for term in searchTerms:
                if term.lower() in task.getDescription().lower() and task.getStatus() != "x":
                    taskListSearched.append(task)
                    break

        deactivatedFilters = [(name, filt, True) for name, filt, _ in self.__filterList]
        return TelegramTaskListManager(taskListSearched, [], [], deactivatedFilters, self.__statistics_service, self.__tasksPerPage)

    def current_view(self) -> TaskView:
        """Return this channel's current view as explicit query parameters."""
        return TaskView(
            filters=tuple(name for name, _, enabled in self.__filterList if enabled),
            page=self.__taskListPage + 1,
            page_size=self.__tasksPerPage,
            algorithm=self.__selectedAlgorithm[0] if self.__selectedAlgorithm else "",
            heuristic=self.__selectedHeuristic[0] if self.__selectedHeuristic else "",
            search=self.__search_terms,
        )

    def clone_for_view(self, tasks: List[ITaskModel], view: TaskView) -> "TelegramTaskListManager":
        """Build a fresh manager for a view without changing this channel's state.

        Algorithms such as GTD, EDF, and SJF keep a mutable explanation string.
        Each query gets distinct strategy instances so interleaved clients cannot
        overwrite one another's descriptions.
        """
        filter_by_name = {name: (name, filterr, False) for name, filterr, _ in self.__filterList}
        if len(view.filters) != len(set(view.filters)):
            raise ValueError("A filter may be selected only once")
        unknown_filters = [name for name in view.filters if name not in filter_by_name]
        if unknown_filters:
            raise ValueError(f"Unknown filter: {unknown_filters[0]}")
        selected_filter_names = set(view.filters)
        selected_filters = [
            (name, filter_obj, name in selected_filter_names)
            for name, filter_obj, _ in self.__filterList
        ]

        heuristic_by_name = {name: heuristic for name, heuristic in self.__heuristicList}
        selected_heuristic = None
        if view.heuristic:
            if view.heuristic not in heuristic_by_name:
                raise ValueError(f"Unknown heuristic: {view.heuristic}")
            selected_heuristic = (view.heuristic, copy.copy(heuristic_by_name[view.heuristic]))
        cloned_heuristics = [(name, copy.copy(heuristic)) for name, heuristic in self.__heuristicList]
        if selected_heuristic is not None:
            selected_heuristic = next(item for item in cloned_heuristics if item[0] == view.heuristic)

        algorithm_by_name = {name: algorithm for name, algorithm in self.__algorithmList}
        selected_algorithm = None
        if view.algorithm:
            if view.algorithm not in algorithm_by_name:
                raise ValueError(f"Unknown algorithm: {view.algorithm}")
            selected_algorithm = (view.algorithm, self._clone_algorithm(algorithm_by_name[view.algorithm]))
        cloned_algorithms = [
            (name, self._clone_algorithm(algorithm))
            for name, algorithm in self.__algorithmList
        ]
        if selected_algorithm is not None:
            selected_algorithm = next(item for item in cloned_algorithms if item[0] == view.algorithm)

        manager = TelegramTaskListManager(
            tasks,
            cloned_algorithms,
            cloned_heuristics,
            selected_filters,
            self.__statistics_service,
            view.page_size,
        )
        manager.__selectedAlgorithm = selected_algorithm
        manager.__selectedHeuristic = selected_heuristic
        manager.__taskListPage = view.page - 1
        manager.__search_terms = view.search
        if view.search:
            manager.__selectedAlgorithm = None
            manager.__selectedHeuristic = None
        return manager

    @staticmethod
    def _clone_algorithm(algorithm: IAlgorithm) -> IAlgorithm:
        cloned = copy.copy(algorithm)
        if hasattr(cloned, "description") and hasattr(cloned, "baseDescription"):
            cloned.description = cloned.baseDescription
        if hasattr(cloned, "category"):
            cloned.category = "all"
        if hasattr(cloned, "orderedHeuristics"):
            cloned.orderedHeuristics = [
                (copy.copy(heuristic), threshold)
                for heuristic, threshold in cloned.orderedHeuristics
            ]
        if hasattr(cloned, "defaultHeuristic"):
            heuristic, threshold = cloned.defaultHeuristic
            cloned.defaultHeuristic = (copy.copy(heuristic), threshold)
        if hasattr(cloned, "calmHeuristic"):
            cloned.calmHeuristic = copy.copy(cloned.calmHeuristic)
        return cloned

    def render_filter_summary(self, taskListString: str) -> str:
        isOnlyFirstFilterActive = len([f for f in self.__filterList if f[2]]) == 1 and self.__filterList[0][2]
        if not isOnlyFirstFilterActive:
            taskListString += "\n\nselected filters: "
            for i, filter in enumerate(self.__filterList):
                if filter[2]:
                    taskListString += f"\n/filter_{i + 1}: {filter[0]}"
        return taskListString

    def update_taskList(self, taskModelList: List[ITaskModel]) -> None:
        self.__taskModelList = taskModelList
        self.__correctSelectedTask()

    def add_task(self, task: ITaskModel) -> None:
        self.__taskModelList.append(task)
        self.__correctSelectedTask()

    def __correctSelectedTask(self) -> None:
        if self.__selectedTask is not None:
            lastSelectedTask = self.__selectedTask
            for task in self.__taskModelList:
                if task.getDescription() == lastSelectedTask.getDescription():
                    self.__selectedTask = task
                    break

    @property
    def selected_algorithm(self) -> None | IAlgorithm:
        """Returns the currently selected algorithm."""
        if not self.__selectedAlgorithm:
            return None
        
        return self.__selectedAlgorithm[1]

    def select_heuristic(self, messageText: str) -> None:
        heuristicIndex = int(messageText.split("_")[1]) - 1
        self.__selectedHeuristic = self.__heuristicList[heuristicIndex]

    def select_filter(self, messageText: str) -> None:
        filterIndex = int(messageText.split("_")[1]) - 1
        self.__filterList[filterIndex] = (
            self.__filterList[filterIndex][0],
            self.__filterList[filterIndex][1],
            not self.__filterList[filterIndex][2]
        )

    def select_algorithm(self, messageText: str) -> None:
        algorithmIndex = int(messageText.split("_")[1]) - 1
        self.__selectedAlgorithm = self.__algorithmList[algorithmIndex]

    def get_filter_list(self) -> FilterListDict:
        retval: FilterListDict = {}
        filterList = retval.get("filterList", [])
        for _, filter_tuple in enumerate(self.__filterList):
            name = filter_tuple[0]
            filter_obj = filter_tuple[1]
            enabled = filter_tuple[2]
            description = getattr(filter_obj, "getDescription", lambda: str(filter_obj))()
            filterList.append(
                FilterEntry(name, description, enabled)
            )
        return {"filterList": filterList}

    def get_heuristic_list(self) -> list[dict[str, str]]:  # Dict must contain heuristic id, name and description
        heuristicList: list[dict[str, str]] = []
        for _, heuristic in enumerate(self.__heuristicList):
            heuristicName, heuristicInstance = heuristic
            heuristicList.append({
                "name": heuristicName,
                "description": heuristicInstance.getDescription()
            })
        return heuristicList

    def get_algorithm_list(self) -> list[dict[str, str]]:  # Dict must contain algorithm id, name and description
        algorithmList: list[dict[str, str]] = []
        for _, algorithm in enumerate(self.__algorithmList):
            algorithmName, algorithmInstance = algorithm
            algorithmList.append({
                "name": algorithmName,
                "description": algorithmInstance.getDescription()
            })
        return algorithmList

    def get_list_stats(self) -> WorkloadStats:
        return self.__statistics_service.getWorkloadStats(self.__taskModelList)
        
    def get_task_list_content(
        self,
        *,
        selected_tasks: List[ITaskModel] | None = None,
    ) -> TaskListContent:
        """
        Returns a dictionary with the content needed to render a task list.
        This includes algorithm information, heuristic information, tasks, pagination details, etc.
        """
        task_list = self.filtered_task_list if selected_tasks is None else selected_tasks
        
        # Get task details for the current page
        start_index = self.__taskListPage * self.__tasksPerPage
        end_index = (self.__taskListPage + 1) * self.__tasksPerPage
        page_tasks = task_list[start_index:end_index]
        
        # Format tasks with complete information
        tasks: list[TaskEntry] = []
        for i, task in enumerate(page_tasks):
            # Get heuristic value for the task
            heuristic_value: float = 0.0
            if len(self.__heuristicList) > 0 and isinstance(self.__selectedHeuristic, tuple):
                cached_scores = self.__last_sorted_scores
                use_cached_score = task_list is self.__last_scored_population
                use_cached_score = use_cached_score and cached_scores is not None
                use_cached_score = use_cached_score and id(task) in (cached_scores or {})
                if use_cached_score and cached_scores is not None:
                    heuristic_value = cached_scores[id(task)]
                else:
                    heuristic_value = self.__selectedHeuristic[1].evaluate(task)
            
            task_id = task.getTaskUID()
            
            tasks.append(TaskEntry(
                id=task_id,
                description=task.getDescription(),
                context=task.getContext(),
                start=str(task.getStart()),
                due=str(task.getDue()),
                severity=task.getSeverity(),
                status=task.getStatus(),
                total_cost=task.getTotalCost().as_pomodoros(),
                effort_invested=task.getInvestedEffort().as_pomodoros(),
                heuristic_value=heuristic_value
            ))
        
        # Get pagination information
        total_pages = (len(task_list) + self.__tasksPerPage - 1) // self.__tasksPerPage if self.__tasksPerPage > 0 else 1
        current_page = self.__taskListPage + 1
        
        # Get algorithm information
        algorithm_name = self.__selectedAlgorithm[0] if len(self.__algorithmList) > 0 and isinstance(self.__selectedAlgorithm, tuple) else "None"
        if len(self.__algorithmList) > 0 and isinstance(self.__selectedAlgorithm, tuple):
            selected_algorithm = self.__selectedAlgorithm[1]
            algorithm_desc = getattr(selected_algorithm, "description", selected_algorithm.getDescription())
        else:
            algorithm_desc = "No algorithm selected"
        
        # Get heuristic information
        sort_heuristic = self.__selectedHeuristic[0] if len(self.__heuristicList) > 0 and isinstance(self.__selectedHeuristic, tuple) else "None"
        
        # Get active filters
        active_filters: list[ActiveFilterEntry] = []
        for i, filter_tuple in enumerate(self.__filterList):
            if filter_tuple[2]:  # If filter is enabled
                active_filters.append(
                    ActiveFilterEntry(
                        name=filter_tuple[0],
                        index=i + 1,
                        description=getattr(filter_tuple[1], "getDescription", lambda: str(filter_tuple[1]))()
                    )
                )
        
        return TaskListContent(
            algorithm_name=algorithm_name,
            algorithm_desc=algorithm_desc,
            sort_heuristic=sort_heuristic,
            tasks=tasks,
            total_tasks=len(task_list),
            current_page=current_page,
            total_pages=total_pages,
            active_filters=active_filters,
            interactive=True  # Default to interactive mode
        )

    def __filter_current_tasks(
        self,
        tasks: List[ITaskModel],
        now: TimePoint | None = None,
    ) -> List[ITaskModel]:
        current_tasks: List[ITaskModel] = []
        query_now = now or TimePoint.now()
        for task in tasks:
            if task.getStatus() != "x" and task.getStart().as_int() < query_now.as_int():
                current_tasks.append(task)
        return current_tasks

    def __sort_by_categories(self, tasks: List[ITaskModel], categories: list[dict[str, str]]) -> List[ITaskModel]:
        sorted_tasks: List[ITaskModel] = []
        for category in categories:
            for task in tasks:
                if task.getContext().startswith(category["prefix"]):
                    sorted_tasks.append(task)
        return sorted_tasks

    def __filter_urgent_tasks(self, date: TimePoint) -> list[ITaskModel]:
        urgent_tasks: list[ITaskModel] = []
        deadline: TimePoint = ((date + TimeAmount("1d")) + TimeAmount("-1s"))
        for task in self.__taskModelList:
            if task.getDue().as_int() < deadline.as_int() and task.getStatus() != "x" and task.getCalm() is False and task.getEventWaited() is None:
                urgent_tasks.append(task)
        return urgent_tasks

    def __filter_and_sort_future_tasks(
        self,
        tasks: List[ITaskModel],
        date: TimePoint,
        now: TimePoint | None = None,
    ) -> List[ITaskModel]:
        sorted_tasks = sorted(tasks, key=lambda x: x.getStart().as_int())
        planned_tasks: List[ITaskModel] = []
        deadline: TimePoint = ((date + TimeAmount("1d")) + TimeAmount("-1s"))
        query_now = now or TimePoint.now()
        for task in sorted_tasks:
            if task.getStart().as_int() > query_now.as_int() and task.getStart().as_int() < deadline.as_int():
                planned_tasks.append(task)
        return planned_tasks

    def __filter_high_heuristic_tasks(
        self,
        urgent_tasks: List[ITaskModel],
        now: TimePoint | None = None,
        tomorrow: TimePoint | None = None,
    ) -> List[ITaskModel]:
        high_heuristic_tasks: List[ITaskModel] = []
        taskModelListTupled: List[Tuple[ITaskModel, float]] = self.__selectedHeuristic[1].sort(self.__taskModelList) if isinstance(self.__selectedHeuristic, tuple) else []
        taskModelList: List[ITaskModel] = [task for task, _ in taskModelListTupled]
        query_now = now or TimePoint.now()
        tomorrow_start = tomorrow or TimePoint.tomorrow()
        urgent_task_objects = {id(task) for task in urgent_tasks}

        for task in taskModelList:
            if id(task) not in urgent_task_objects and task.getStatus() != "x" and task.getStart().as_int() < query_now.as_int() and task.getDue().as_int() >= tomorrow_start.as_int() and task.getCalm() is False and task.getEventWaited() is None:
                high_heuristic_tasks.append(task)

        return high_heuristic_tasks

    def get_day_agenda_content(self, date: TimePoint, categories: list[dict[str, str]]) -> AgendaContent:
        """
        Returns a dictionary with the content needed to render a day agenda.
        This includes active urgent tasks, planned urgent tasks, and other tasks.
        
        Args:
            date: The date for which to get the agenda
            categories: A list of category dictionaries to use for sorting tasks
            
        Returns:
            A dictionary containing the agenda data
        """
        # Get tasks by different criteria
        urgent_tasks = self.__filter_urgent_tasks(date)
        query_now = TimePoint.now()
        tomorrow_day = query_now.datetime_representation.date() + datetime.timedelta(days=1)
        tomorrow = TimePoint(datetime.datetime.combine(tomorrow_day, datetime.time.min))
        current_urgent_tasks = self.__filter_current_tasks(urgent_tasks, query_now)
        current_urgents_by_categories = self.__sort_by_categories(current_urgent_tasks, categories)
        urgent_tasks_by_start = self.__filter_and_sort_future_tasks(urgent_tasks, date, query_now)
        other_tasks = self.__filter_high_heuristic_tasks(urgent_tasks, query_now, tomorrow)
        
        # Format the active urgent tasks
        active_urgent_tasks: list[TaskEntry] = []
        for _, task in enumerate(current_urgents_by_categories):
            task_id = task.getTaskUID()
            
            active_urgent_tasks.append(
                TaskEntry(
                    id=task_id,
                    description=task.getDescription(),
                    context=task.getContext(),
                    start=str(task.getStart()),
                    due=str(task.getDue()),
                    severity=task.getSeverity(),
                    status=task.getStatus(),
                    total_cost=task.getTotalCost().as_pomodoros(),
                    effort_invested=task.getInvestedEffort().as_pomodoros(),
                    heuristic_value=0.0
                )
            )

        # Format the planned urgent tasks
        planned_urgent_tasks: list[TaskEntry] = []
        planned_tasks_by_date: dict[str, list[TaskEntry]] = {}
        
        for _, task in enumerate(urgent_tasks_by_start):
            task_id = task.getTaskUID()
            
            task_data = TaskEntry(
                id=task_id,
                description=task.getDescription(),
                context=task.getContext(),
                start=str(task.getStart()),
                due=str(task.getDue()),
                severity=task.getSeverity(),
                status=task.getStatus(),
                total_cost=task.getTotalCost().as_pomodoros(),
                effort_invested=task.getInvestedEffort().as_pomodoros(),
                heuristic_value=0.0
            )
            
            start_date = str(task.getStart())
            if start_date not in planned_tasks_by_date:
                planned_tasks_by_date[start_date] = []
            
            planned_tasks_by_date[start_date].append(task_data)
            planned_urgent_tasks.append(task_data)
            
        # Format the other tasks
        other_tasks_formatted: list[TaskEntry] = []
        for _, task in enumerate(other_tasks):
            task_id = task.getTaskUID()
            
            other_tasks_formatted.append(
                TaskEntry(
                    id=task_id,
                    description=task.getDescription(),
                    context=task.getContext(),
                    start=str(task.getStart()),
                    due=str(task.getDue()),
                    severity=task.getSeverity(),
                    status=task.getStatus(),
                    total_cost=task.getTotalCost().as_pomodoros(),
                    effort_invested=task.getInvestedEffort().as_pomodoros(),
                    heuristic_value=0.0
                )
            )
            
        # If needed, get task list information for other tasks
        other_task_list_info: TaskListContent | None = None
        if other_tasks:
            other_task_manager = TelegramTaskListManager(
                other_tasks,
                self.__algorithmList,
                self.__heuristicList,
                self.__filterList,
                self.__statistics_service
            )
            other_task_list_info = other_task_manager.get_task_list_content()
            other_task_list_info.interactive = False

        # Return the complete agenda data structure
        return AgendaContent(
            date,
            active_urgent_tasks,
            planned_urgent_tasks,
            planned_tasks_by_date,
            other_tasks_formatted,
            other_task_list_info
        )
        
    def get_task_information(self, task: ITaskModel, taskProvider: ITaskProvider, extended: bool) -> TaskInformation:
        """
        Returns a dictionary with the content needed to render task information.
        This includes task details like description, context, start date, due date,
        total cost, remaining cost, severity, and optional extended information like
        heuristic values and metadata.
        
        Args:
            task: The task for which to get information
            taskProvider: The task provider to get metadata from
            extended: Whether to include extended information like heuristics and metadata
            
        Returns:
            A dictionary containing the task information data
        """
        # Use the same current provider identity as task-list queries and
        # direct reads. These provider identifiers are currently provisional.
        task_id = task.getTaskUID()
        
        # Calculate task costs
        remaining_cost = max(task.getTotalCost().as_pomodoros(), 0.0)
        effort_invested = max(task.getInvestedEffort().as_pomodoros(), 0.0)
        total_cost = remaining_cost + effort_invested
        
        # Basic task information
        task_info = TaskEntry(
            id=task_id,
            description=task.getDescription(),
            context=task.getContext(),
            start=str(task.getStart()),
            due=str(task.getDue()),
            severity=task.getSeverity(),
            status=task.getStatus(),
            total_cost=total_cost,
            effort_invested=task.getInvestedEffort().as_pomodoros(),
            heuristic_value=0.0
        )
        
        # Extended information (heuristics and metadata)
        extendedTaskInfo = None

        if extended:
            heuristics: list[TaskHeuristicsInfo] = []
            for heuristic_name, heuristic_instance in self.__heuristicList:
                heuristics.append(
                    TaskHeuristicsInfo(
                        heuristic_name,
                        heuristic_instance.evaluate(task),
                        heuristic_instance.getComment(task)
                    )
                )
            
            extendedTaskInfo = ExtendedTaskInformation(
                heuristics=heuristics,
                metadata=taskProvider.getTaskMetadata(task)
            )
        
        return TaskInformation(task_info, extendedTaskInfo)
