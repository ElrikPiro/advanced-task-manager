from abc import ABC, abstractmethod
from typing import List

from ..wrappers.TimeManagement import TimePoint

from .ITaskProvider import ITaskProvider
from .ITaskModel import ITaskModel


class ITaskListManager(ABC):

    @property
    @abstractmethod
    def filtered_task_list(self) -> List[ITaskModel]:
        pass

    @property
    @abstractmethod
    def selected_task(self) -> ITaskModel:
        pass

    @selected_task.setter
    @abstractmethod
    def selected_task(self, task: ITaskModel):
        pass

    @abstractmethod
    def reset_pagination(self, tasksPerPage: int = 5):
        pass

    @abstractmethod
    def next_page(self):
        pass

    @abstractmethod
    def prior_page(self):
        pass

    @abstractmethod
    def select_task(self, message: str):
        pass

    @abstractmethod
    def clear_selected_task(self):
        pass

    @abstractmethod
    def search_tasks(self, searchTerms: List[str]):
        pass

    @abstractmethod
    def render_task_list_str_legacy(self, interactive: bool = True) -> str:
        pass

    @abstractmethod
    def update_taskList(self, taskModelList: List[ITaskModel]):
        pass

    @abstractmethod
    def add_task(self, task: ITaskModel):
        pass

    @abstractmethod
    def select_heuristic(self, messageText: str):
        pass

    @abstractmethod
    def select_filter(self, messageText: str):
        pass

    @abstractmethod
    def get_filter_list(self) -> dict:
        pass

    @abstractmethod
    def get_heuristic_list_legacy(self) -> str:
        pass

    @abstractmethod
    def get_list_stats_legacy(self) -> str:
        """
        Returns a string with the statistics of the task list.
        This includes workload, remaining effort, heuristic value, and offender task.
        """
        pass

    @abstractmethod
    def get_list_stats(self) -> dict:
        """
        Returns a dictionary with the statistics of the task list.
        This includes workload, remaining effort, heuristic value, and offender task.
        """
        pass

    @abstractmethod
    def render_task_information(self, task: ITaskModel, taskProvider: ITaskProvider, extended: bool) -> str:
        pass

    @abstractmethod
    def render_day_agenda(self, date: TimePoint, categories: list[dict]) -> str:
        pass

    @abstractmethod
    def get_heuristic_list(self) -> dict:
        pass

    @abstractmethod
    def get_algorithm_list_legacy(self) -> str:
        pass

    @abstractmethod
    def get_algorithm_list(self) -> dict:
        pass

    @abstractmethod
    def get_task_list_content(self) -> dict:
        """
        Returns a dictionary with the content needed to render a task list.
        This includes algorithm information, heuristic information, tasks, pagination details, etc.
        """
        pass
        
    @abstractmethod
    def get_day_agenda_content(self, date: TimePoint, categories: list[dict]) -> dict:
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
