import datetime
from typing import Tuple

from ..Interfaces.IFilter import IFilter
from ..Interfaces.IHeuristic import IHeuristic
from ..Interfaces.ITaskModel import ITaskModel
from ..wrappers.TimeManagement import TimePoint

class GtdTaskFilter(IFilter):

    def __init__(self, activeFilter : IFilter, orderedCategories : list[IFilter], orderedHeuristics : list[(IHeuristic, float)], defaultHeuristic : Tuple[IHeuristic, float]):
        self.activeFilter = activeFilter
        self.orderedCategories = orderedCategories
        self.orderedHeuristics = orderedHeuristics
        self.defaultHeuristic = defaultHeuristic
        self.baseDescription = "GTD Task Filter"
        self.description = self.baseDescription
        self.category = "all"
        pass

    def filter(self, tasks : list[ITaskModel]) -> list:
        activeTasks = self.activeFilter.filter(tasks) if self.activeFilter != None else tasks
        
        # get all task with due date before now
        retval = self._filterUrgents(activeTasks)
        retval = self._filterOrderedCategories(retval)

        if len(retval) > 0:
            self.description = f"{self.baseDescription} \n    - Urgent tasks ({self.category})"
            return retval
        
        # get all task with heuristic value above threshold and NOT calm
        for heuristic, threshold in self.orderedHeuristics:
            retval = self._filterByHeuristic(heuristic, threshold, activeTasks)
            retval = self._filterCalmTasks(retval)
            retval = self._filterOrderedCategories(retval)
            if len(retval) > 0:
                self.description = f"{self.baseDescription} \n    - {heuristic.__class__.__name__} >= {threshold} ({self.category})"
                return retval
            
        # get all task with heuristic value above threshold and calm
        for heuristic, threshold in self.orderedHeuristics:
            retval = self._filterByHeuristic(heuristic, threshold, activeTasks)
            retval = self._filterCalmTasks(retval, False)
            if len(retval) > 0:
                self.description = f"{self.baseDescription} \n    - {heuristic.__class__.__name__} >= {threshold} (CALM)"
                return retval
            
        # get default working model
        heuristic, threshold = self.defaultHeuristic
        retval = self._filterByHeuristic(heuristic, threshold, activeTasks)
        
        self.description = f"{self.baseDescription} \n    - {heuristic.__class__.__name__} >= {threshold} (default)"
        return retval
    
    def getDescription(self) -> str:
        return self.description
        
    
    def _filterUrgents(self, tasks : list[ITaskModel]) -> list:
        retval = []
        for task in tasks:
            if task.getDue().datetime_representation.timestamp() < TimePoint.now().datetime_representation.timestamp():
                retval.append(task)
        return retval
    
    def _filterOrderedCategories(self, tasks : list[ITaskModel]) -> list:
        filteredTasks = []
        for description, category in self.orderedCategories:
            filteredTasks = category.filter(tasks)
            if len(filteredTasks) == 0:
                continue
            else:
                self.category = description
                break
        return filteredTasks
    
    def _filterByHeuristic(self, heuristic : IHeuristic, threshold : float, tasks : list[ITaskModel]) -> list:
        retval = []
        for task in tasks:
            if heuristic.evaluate(task) >= threshold:
                retval.append(task)
        return retval
    
    def _filterCalmTasks(self, tasks : list[ITaskModel], notCalm : bool = True) -> list:
        retval = []
        for task in tasks:
            if task.getCalm() ^ notCalm:
                retval.append(task)
        return retval
