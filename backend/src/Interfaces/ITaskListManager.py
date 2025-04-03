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
    def render_task_list_str(self, interactive: bool = True) -> str:
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
    def get_filter_list(self) -> str:
        pass

    @abstractmethod
    def get_heuristic_list(self) -> str:
        pass

    @abstractmethod
    def get_list_stats(self) -> str:
        """
        Returns a string with the statistics of the task list.
        This includes workload, remaining effort, heuristic value, and offender task.
        """
        pass

    @abstractmethod
    def render_task_information(self, task: ITaskModel, taskProvider: ITaskProvider, extended: bool) -> str:
        pass

    @abstractmethod
    def render_day_agenda(self, date: TimePoint, categories: list[dict]) -> str:
        pass
