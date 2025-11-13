from typing import List, Tuple

from .Utils import ActiveFilterEntry, AgendaContent, ExtendedTaskInformation, FilterListDict, FilterEntry, TaskEntry, TaskHeuristicsInfo, TaskInformation, TaskListContent, WorkloadStats

from .wrappers.TimeManagement import TimeAmount, TimePoint

from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskListManager import ITaskListManager
from .algorithms.Interfaces.IAlgorithm import IAlgorithm


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

        self.reset_pagination(tasksPerPage)

    @property
    def filtered_task_list(self) -> List[ITaskModel]:

        newTaskList: List[ITaskModel] = []

        for task in self.__taskModelList:
            for filterr in self.__filterList:
                if filterr[2] and filterr[1].filter([task]):
                    newTaskList.append(task)
                    break

        if isinstance(self.__selectedHeuristic, tuple):
            heuristic: IHeuristic = self.__selectedHeuristic[1]
            sortedTaskList: List[Tuple[ITaskModel, float]] = heuristic.sort(newTaskList)
            newTaskList = [task for task, _ in sortedTaskList]

        if isinstance(self.__selectedAlgorithm, tuple):
            algorithm: IAlgorithm = self.__selectedAlgorithm[1]
            newTaskList = algorithm.apply(newTaskList)

        return newTaskList

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

        return TelegramTaskListManager(taskListSearched, [], [], self.__filterList, self.__statistics_service, self.__tasksPerPage)

    def render_filter_summary(self, taskListString: str) -> str:
        isOnlyFirstFilterActive = len([f for f in self.__filterList if f[2]]) == 1 and self.__filterList[0][2]
        if not isOnlyFirstFilterActive:
            taskListString += "\n\nselected filters: "
            for i, filter in enumerate(self.__filterList):
                if filter[2]:
                    taskListString += f"\n/filter_{i+1}: {filter[0]}"
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
        
    def get_task_list_content(self) -> TaskListContent:
        """
        Returns a dictionary with the content needed to render a task list.
        This includes algorithm information, heuristic information, tasks, pagination details, etc.
        """
        task_list = self.filtered_task_list
        
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
                heuristic_value = self.__selectedHeuristic[1].evaluate(task)
            
            # Use hash of description as ID if getId is not available
            task_id = getattr(task, "getId", lambda: str(i + 1))()
            
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
        algorithm_desc = self.__selectedAlgorithm[1].getDescription() if len(self.__algorithmList) > 0 and isinstance(self.__selectedAlgorithm, tuple) else "No algorithm selected"
        
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

    def __filter_current_tasks(self, tasks: List[ITaskModel]) -> List[ITaskModel]:
        current_tasks: List[ITaskModel] = []
        for task in tasks:
            if task.getStatus() != "x" and task.getStart().as_int() < TimePoint.now().as_int():
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
            if task.getDue().as_int() < deadline.as_int() and task.getStatus() != "x":
                urgent_tasks.append(task)
        return urgent_tasks

    def __filter_and_sort_future_tasks(self, tasks: List[ITaskModel], date: TimePoint) -> List[ITaskModel]:
        sorted_tasks = sorted(tasks, key=lambda x: x.getStart().as_int())
        planned_tasks: List[ITaskModel] = []
        deadline: TimePoint = ((date + TimeAmount("1d")) + TimeAmount("-1s"))
        for task in sorted_tasks:
            if task.getStart().as_int() > TimePoint.now().as_int() and task.getStart().as_int() < deadline.as_int():
                planned_tasks.append(task)
        return planned_tasks

    def __filter_high_heuristic_tasks(self, urgent_tasks: List[ITaskModel]) -> List[ITaskModel]:
        high_heuristic_tasks: List[ITaskModel] = []
        taskModelListTupled: List[Tuple[ITaskModel, float]] = self.__selectedHeuristic[1].sort(self.__taskModelList) if isinstance(self.__selectedHeuristic, tuple) else []
        taskModelList: List[ITaskModel] = [task for task, _ in taskModelListTupled]

        for task in taskModelList:
            if task not in urgent_tasks and task.getStatus() != "x" and task.getStart().as_int() < TimePoint.now().as_int() and task.getDue().as_int() >= TimePoint.tomorrow().as_int():
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
        current_urgent_tasks = self.__filter_current_tasks(urgent_tasks)
        current_urgents_by_categories = self.__sort_by_categories(current_urgent_tasks, categories)
        urgent_tasks_by_start = self.__filter_and_sort_future_tasks(urgent_tasks, date)
        other_tasks = self.__filter_high_heuristic_tasks(urgent_tasks)
        
        # Format the active urgent tasks
        active_urgent_tasks: list[TaskEntry] = []
        for i, task in enumerate(current_urgents_by_categories):
            # Use task description hash as ID if getId is not available
            task_id = getattr(task, "getId", lambda: f"active_{i}")()
            
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
        
        for i, task in enumerate(urgent_tasks_by_start):
            # Use task description hash as ID if getId is not available
            task_id = getattr(task, "getId", lambda: f"planned_{i}")()
            
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
        for i, task in enumerate(other_tasks):
            # Use task description hash as ID if getId is not available
            task_id = getattr(task, "getId", lambda: f"other_{i}")()
            
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
        # Get task ID safely
        task_id = getattr(task, "getId", lambda: "unknown")()
        
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
