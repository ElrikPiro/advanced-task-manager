from typing import List, Tuple
from .wrappers.TimeManagement import TimeAmount, TimePoint

from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.ITaskListManager import ITaskListManager


class TelegramTaskListManager(ITaskListManager):
    
    def __init__(self, taskModelList: List[ITaskModel], heuristics : List[Tuple[str, IHeuristic]], filters : List[Tuple[str, IFilter]], statistics_service : IStatisticsService, tasksPerPage: int = 5):
        
        self.__taskModelList = taskModelList

        self.__selectedTask = None
        
        self.__heuristicList = heuristics
        self.__selectedHeuristic = heuristics[0] if len(heuristics) > 0 else None
        
        self.__filterList = filters
        self.__selectedFilter = filters[0] if len(filters) > 0 else None

        self.__statistics_service = statistics_service

        self.reset_pagination(tasksPerPage)
    
    @property
    def filtered_task_list(self) -> List[ITaskModel]:
        
        newTaskList : List[ITaskModel] = self.__taskModelList

        if len(self.__filterList) > 0:
            selectedFilter : IFilter = self.__selectedFilter[1]
            newTaskList = selectedFilter.filter(newTaskList)

        if len(self.__heuristicList) > 0:
            heuristic : IHeuristic = self.__selectedHeuristic[1]
            sortedTaskList : List[Tuple[ITaskModel, float]] = heuristic.sort(newTaskList)
            newTaskList = [task for task, _ in sortedTaskList]

        return newTaskList
    
    @property
    def selected_task(self) -> ITaskModel:
        return self.__selectedTask
    
    @selected_task.setter
    def selected_task(self, task: ITaskModel):
        self.__selectedTask = task

    def reset_pagination(self, tasksPerPage: int = 5):
        self.__taskListPage = 0
        self.__tasksPerPage = tasksPerPage

    def next_page(self):
        self.__taskListPage += 1
    
    def prior_page(self):
        if self.__taskListPage > 0:
            self.__taskListPage -= 1
    
    def select_task(self, message: str):
        task_list = self.filtered_task_list
        taskId = int(message.split("_")[1]) - 1
        offset = self.__taskListPage * self.__tasksPerPage
        if 0 <= taskId < len(task_list):
            self.__selectedTask = task_list[taskId + offset]
        else:
            self.__selectedTask = None

    def clear_selected_task(self):
        self.__selectedTask = None

    def search_tasks(self, searchTerms: List[str]):
        taskListSearched = []
        for task in self.__taskModelList:
            for term in searchTerms:
                if term in task.getDescription() and task.getStatus() != "x":
                    taskListSearched.append(task)
                    break

        return TelegramTaskListManager(taskListSearched, [], [], self.__statistics_service, self.__tasksPerPage)

    def render_task_list_str(self, interactive: bool = True) -> str:
        task_list = self.filtered_task_list
        interactiveId = "/task_" if interactive else ""

        subTaskList = task_list[self.__taskListPage * self.__tasksPerPage : (self.__taskListPage + 1) * self.__tasksPerPage]
        subTaskListDescriptions = [(f"{interactiveId}{i+1} : {task.getDescription()}") for i, task in enumerate(subTaskList)]

        taskListString = "\n".join(subTaskListDescriptions)
        if interactive:
            totalPages = (len(task_list) + self.__tasksPerPage - 1) // self.__tasksPerPage
            taskListString += "\n\nPage " + str(self.__taskListPage + 1) + " of " + str(totalPages) + "\n"
            taskListString += "/next - Next page\n/previous - Previous page"
            taskListString += "\n\nselected /heuristic : " + self.__selectedHeuristic[0]
            taskListString += "\nselected /filter : " + self.__selectedFilter[1].getDescription()
        
        return taskListString
    
    def update_taskList(self, taskModelList: List[ITaskModel]):
        self.__taskModelList : List[ITaskModel] = taskModelList
        self.__correctSelectedTask()

    def add_task(self, task: ITaskModel):
        self.__taskModelList.append(task)
        self.__correctSelectedTask()

    def __correctSelectedTask(self):
        if self.__selectedTask is not None:
            lastSelectedTask = self.__selectedTask
            for task in self.__taskModelList:
                if task.getDescription() == lastSelectedTask.getDescription():
                    self.__selectedTask = task
                    break
    
    def select_heuristic(self, messageText: str):
        heuristicIndex = int(messageText.split("_")[1]) - 1
        self.__selectedHeuristic = self.__heuristicList[heuristicIndex]

    def select_filter(self, messageText: str):
        filterIndex = int(messageText.split("_")[1]) - 1
        self.__selectedFilter = self.__filterList[filterIndex]

    def get_filter_list(self) -> str:
        filterList = "\n".join([f"/filter_{i+1} : {filter[0]}" for i, filter in enumerate(self.__filterList)])
        filterList += "\n\n/heuristic - List heuristic options"
        return filterList

    def get_heuristic_list(self) -> str:
        heuristicList = "\n".join([f"/heuristic_{i+1} : {heuristic[0]}" for i, heuristic in enumerate(self.__heuristicList)])
        heuristicList += "\n\n/filter - List filter options"
        return heuristicList

    def get_list_stats(self) -> str:
        statsMessage = "Work done in the last 7 days:\n"
        statsMessage += "`|    Date    | Work Done |`\n"
        statsMessage += "`|------------|-----------|`\n"
        totalWork : TimeAmount = TimeAmount("0")
        for i in range(7):
            date : TimePoint = TimePoint.today() + TimeAmount(f"-{i}d")
            workDone : TimeAmount = self.__statistics_service.getWorkDone(date)
            totalWork += workDone
            statsMessage += f"`| {date} |    {round(workDone.as_pomodoros(), 1)}    |`\n"
        # add average work done per day
        statsMessage += "`|------------|-----------|`\n"
        statsMessage += f"`|   Average  |    {round(totalWork.as_pomodoros()/7, 1)}    |`\n"
        statsMessage += "`|------------|-----------|`\n\n"

        statsMessage += "Workload statistics:\n"
        workloadStats = self.__statistics_service.getWorkloadStats(self.__taskModelList)
        workload = workloadStats[0]
        remEffort = workloadStats[1]
        heuristicValue = workloadStats[2]
        heuristicName = workloadStats[3]
        offender = workloadStats[4]
        offenderMax = workloadStats[5]

        statsMessage += f"`current workload: {workload} per day`\n"
        statsMessage += f"    `max Offender: '{offender}' with {offenderMax} per day`\n"
        statsMessage += f"`total remaining effort: {remEffort}`\n"
        statsMessage += f"`max {heuristicName}: {heuristicValue}`\n\n"
        statsMessage += "/list - return back to the task list"
        return statsMessage

    def render_task_information(self, task : ITaskModel, taskProvider : ITaskProvider, extended : bool) -> str:
        taskDescription = task.getDescription()
        taskContext = task.getContext()
        taskSeverity = task.getSeverity()
        taskStartDate : TimePoint = task.getStart()
        taskDueDate : TimePoint = task.getDue()
        taskRemainingCost : TimeAmount = TimeAmount(f"{max(task.getTotalCost().as_pomodoros(), 0.0)}p")
        taskEffortInvested : float = max(task.getInvestedEffort().as_pomodoros(), 0)
        taskTotalCost = TimeAmount(f"{max(task.getTotalCost().as_pomodoros(), 0.0)+taskEffortInvested}p")
        
        taskInformation = f"Task: {taskDescription}\nContext: {taskContext}\nStart Date: {taskStartDate}\nDue Date: {taskDueDate}\nTotal Cost: {taskTotalCost}\nRemaining: {taskRemainingCost}\nSeverity: {taskSeverity}"
        
        if extended:
            for i, heuristic in enumerate(self.__heuristicList):
                heuristicName, heuristicInstance = heuristic
                taskInformation += f"\n{heuristicName} : " + heuristicInstance.getComment(task)
            
            taskInformation += f"\n\n<b>Metadata:</b><code>{taskProvider.getTaskMetadata(task)}</code>"

        taskInformation += "\n\n/list - Return to list"
        taskInformation += "\n/done - Mark task as done"
        taskInformation += "\n/set [param] [value] - Set task parameter"
        taskInformation += "\n\tparameters: description, context, start, due, severity, total\\_cost, effort\\_invested, calm"
        taskInformation += "\n/work [work_units] - invest work units in the task"
        taskInformation += "\n/snooze - snooze the task for 5 minutes"
        taskInformation += "\n/info - Show extended information"
        return taskInformation
