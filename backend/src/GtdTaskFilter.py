import datetime
from typing import Tuple

from .Interfaces.IFilter import IFilter
from .Interfaces.IHeuristic import IHeuristic
from .Interfaces.ITaskModel import ITaskModel

class GtdTaskFilter(IFilter):

    def __init__(self, activeFilter : IFilter, orderedCategories : list[IFilter], orderedHeuristics : list[(IHeuristic, float)], defaultHeuristic : Tuple[IHeuristic, float]):
        self.activeFilter = activeFilter
        self.orderedCategories = orderedCategories
        self.orderedHeuristics = orderedHeuristics
        self.defaultHeuristic = defaultHeuristic
        pass

    def filter(self, tasks : list[ITaskModel]) -> list:
        activeTasks = self.activeFilter.filter(tasks) if self.activeFilter != None else tasks
        
        # get all task with due date before now
        retval = self._filterUrgents(activeTasks)
        retval = self._filterOrderedCategories(retval)

        if len(retval) > 0:
            return retval
        
        # get all task with heuristic value above threshold
        for heuristic, threshold in self.orderedHeuristics:
            retval = self._filterByHeuristic(heuristic, threshold, activeTasks)
            retval = self._filterOrderedCategories(retval)
            retval = self._filterCalmTasks(retval)
            if len(retval) > 0:
                return retval
            
        # get default working model
        heuristic, threshold = self.defaultHeuristic
        retval = self._filterByHeuristic(heuristic, threshold, activeTasks)
        
        return retval
        
    
    def _filterUrgents(self, tasks : list[ITaskModel]) -> list:
        retval = []
        for task in tasks:
            if task.getDue()/1000.0 < datetime.datetime.now().timestamp():
                retval.append(task)
        return retval
    
    def _filterOrderedCategories(self, tasks : list[ITaskModel]) -> list:
        filteredTasks = []
        for description, category in self.orderedCategories:
            filteredTasks = category.filter(tasks)
            if len(filteredTasks) == 0:
                continue
            else:
                break
        return filteredTasks
    
    def _filterByHeuristic(self, heuristic : IHeuristic, threshold : float, tasks : list[ITaskModel]) -> list:
        retval = []
        for task in tasks:
            if heuristic.evaluate(task) >= threshold:
                retval.append(task)
        return retval
    
    def _filterCalmTasks(self, tasks : list[ITaskModel]) -> list:
        retval = []
        for task in tasks:
            if not task.getCalm():
                retval.append(task)
        return retval