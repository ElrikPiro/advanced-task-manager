from abc import ABC, abstractmethod
from typing import List

from src.algorithms.Interfaces.IAlgorithm import IAlgorithm
from src.wrappers.TimeManagement import TimePoint
from src.Utils import FilterListDict, TaskListContent, WorkloadStats, AgendaContent, TaskInformation

from .ITaskProvider import ITaskProvider
from .ITaskModel import ITaskModel


class ITaskListManager(ABC):

    @property
    @abstractmethod
    def filtered_task_list(self) -> List[ITaskModel]:
        pass

    @property
    @abstractmethod
    def selected_task(self) -> ITaskModel | None:
        pass

    @selected_task.setter
    @abstractmethod
    def selected_task(self, task: ITaskModel | None) -> None:
        pass

    @abstractmethod
    def reset_pagination(self, tasksPerPage: int = 5) -> None:
        pass

    @abstractmethod
    def next_page(self) -> None:
        pass

    @abstractmethod
    def prior_page(self) -> None:
        pass

    @abstractmethod
    def select_task(self, message: str) -> None:
        pass

    @abstractmethod
    def clear_selected_task(self) -> None:
        pass

    @abstractmethod
    def search_tasks(self, searchTerms: List[str]) -> "ITaskListManager":
        pass

    @abstractmethod
    def update_taskList(self, taskModelList: List[ITaskModel]) -> None:
        pass

    @abstractmethod
    def add_task(self, task: ITaskModel) -> None:
        pass

    @abstractmethod
    def select_heuristic(self, messageText: str) -> None:
        pass

    @abstractmethod
    def select_filter(self, messageText: str) -> None:
        pass

    @abstractmethod
    def get_filter_list(self) -> FilterListDict:
        pass

    @abstractmethod
    def get_list_stats(self) -> WorkloadStats:
        """
        Returns a dictionary with the statistics of the task list.
        This includes workload, remaining effort, heuristic value, and offender task.
        """
        pass

    @abstractmethod
    def get_heuristic_list(self) -> dict[str, list[dict[str, str]]]:
        pass

    @abstractmethod
    def get_algorithm_list(self) -> dict[str, list[dict[str, str]]]:
        pass

    @abstractmethod
    def get_task_list_content(self) -> TaskListContent:
        """
        Returns a dictionary with the content needed to render a task list.
        This includes algorithm information, heuristic information, tasks, pagination details, etc.
        """
        pass
        
    @abstractmethod
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
        pass
        
    @abstractmethod
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
        pass

    @property
    @abstractmethod
    def selected_algorithm(self) -> IAlgorithm | None:
        pass

    @abstractmethod
    def select_algorithm(self, messageText: str) -> None:
        pass
