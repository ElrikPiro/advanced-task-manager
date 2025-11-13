import unittest
from unittest.mock import MagicMock
from src.TelegramTaskListManager import TelegramTaskListManager
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class TestTelegramTaskListManager(unittest.TestCase):

    def setUp(self):
        # Create mock task models
        self.task1 = MagicMock()
        self.task1.getDescription.return_value = "Task 1"
        self.task1.getStatus.return_value = ""
        self.task1.getContext.return_value = "catA:foo"
        self.task1.getDue.return_value = MagicMock(as_int=MagicMock(return_value=2000))
        self.task1.getStart.return_value = MagicMock(as_int=MagicMock(return_value=500))

        self.task2 = MagicMock()
        self.task2.getDescription.return_value = "Task 2"
        self.task2.getStatus.return_value = ""
        self.task2.getContext.return_value = "catB:bar"
        self.task2.getDue.return_value = MagicMock(as_int=MagicMock(return_value=3000))
        self.task2.getStart.return_value = MagicMock(as_int=MagicMock(return_value=1500))

        self.task3 = MagicMock()
        self.task3.getDescription.return_value = "Task 3"
        self.task3.getStatus.return_value = ""
        self.task3.getContext.return_value = "catA:baz"
        self.task3.getDue.return_value = MagicMock(as_int=MagicMock(return_value=4000))
        self.task3.getStart.return_value = MagicMock(as_int=MagicMock(return_value=2500))

        self.task_list = [self.task1, self.task2, self.task3]

        # Create mock statistics service
        self.statistics_service = MagicMock()

        # Create mock heuristics and filters (filters must be 3-tuples)
        self.heuristics = [("Priority", MagicMock())]
        self.filters = [("Active", MagicMock(), True)]

        # Create the task list manager
        self.task_list_manager = TelegramTaskListManager(
            self.task_list,
            [],
            self.heuristics,
            self.filters,
            self.statistics_service
        )

    def test__sort_by_categories(self):
        categories = [{"prefix": "catA:"}, {"prefix": "catB:"}]
        result = self.task_list_manager._TelegramTaskListManager__sort_by_categories(self.task_list, categories)
        self.assertEqual(result[0].getDescription(), "Task 1")
        self.assertEqual(result[1].getDescription(), "Task 3")
        self.assertEqual(result[2].getDescription(), "Task 2")

    def test__filter_urgent_tasks(self):
        date = MagicMock()
        date.__add__.side_effect = lambda x: date
        date.__radd__ = date.__add__
        (date + TimeAmount("1d") + TimeAmount("-1s")).as_int.return_value = 2500
        # Patch getDue().as_int() to return unique ints for each task
        self.task1.getDue.return_value.as_int.return_value = 2000
        self.task2.getDue.return_value.as_int.return_value = 3000
        self.task3.getDue.return_value.as_int.return_value = 4000
        result = self.task_list_manager._TelegramTaskListManager__filter_urgent_tasks(date)
        self.assertIn(self.task1, result)
        self.assertNotIn(self.task2, result)
        self.assertNotIn(self.task3, result)

    def test__filter_and_sort_future_tasks(self):
        date = MagicMock()
        date.__add__.side_effect = lambda x: date
        date.__radd__ = date.__add__
        (date + TimeAmount("1d") + TimeAmount("-1s")).as_int.return_value = 3000
        TimePoint.now = staticmethod(lambda: MagicMock(as_int=MagicMock(return_value=1000)))
        # Patch getStart().as_int() to return unique, sortable ints
        self.task1.getStart.return_value.as_int.return_value = 500
        self.task2.getStart.return_value.as_int.return_value = 1500
        self.task3.getStart.return_value.as_int.return_value = 2500
        result = self.task_list_manager._TelegramTaskListManager__filter_and_sort_future_tasks(self.task_list, date)
        self.assertIn(self.task3, result)
        self.assertIn(self.task2, result)
        self.assertNotIn(self.task1, result)

    def test_filtered_task_list_with_active_filter(self):
        # Only task1 passes the filter
        class Filter:
            def filter(self_inner, tasks):
                t = tasks[0]
                return [t] if t is self.task1 else []
        filter_mock = Filter()
        filters = [("Active", filter_mock, True)]
        self.task1.getDescription.return_value = "Task 1"
        self.task2.getDescription.return_value = "Task 2"
        self.task3.getDescription.return_value = "Task 3"
        manager = TelegramTaskListManager(self.task_list, [], self.heuristics, filters, self.statistics_service)
        manager._TelegramTaskListManager__heuristicList = []
        manager._TelegramTaskListManager__selectedHeuristic = None
        filtered = manager.filtered_task_list
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].getDescription(), "Task 1")

    def test_filtered_task_list_with_no_active_filter(self):
        # No filters enabled, should return all tasks (no filtering)
        filters = [("Active", MagicMock(), False)]
        manager = TelegramTaskListManager(self.task_list, [], self.heuristics, filters, self.statistics_service)
        # Heuristic sort will be called, so mock it to return tasks in reverse order
        heuristic_mock = MagicMock()
        heuristic_mock.sort.return_value = list(reversed([(t, 0) for t in self.task_list]))
        manager._TelegramTaskListManager__heuristicList = [("Priority", heuristic_mock)]
        manager._TelegramTaskListManager__selectedHeuristic = ("Priority", heuristic_mock)
        filtered = manager.filtered_task_list
        self.assertEqual(filtered, list(reversed(self.task_list)))


class TestTelegramTaskListManagerAdditional(unittest.TestCase):

    def setUp(self):
        # Create mock task models
        self.task1 = MagicMock()
        self.task1.getDescription.return_value = "Task 1"
        self.task1.getStatus.return_value = ""

        self.task2 = MagicMock()
        self.task2.getDescription.return_value = "Task 2"
        self.task2.getStatus.return_value = ""

        self.task3 = MagicMock()
        self.task3.getDescription.return_value = "Task 3"
        self.task3.getStatus.return_value = ""

        self.task_list = [self.task1, self.task2, self.task3]

        # Create mock statistics service
        self.statistics_service = MagicMock()

        # Create mock heuristics and filters
        self.heuristics = [("Priority", MagicMock())]
        self.filters = [("Active", MagicMock())]

        # Create the task list manager
        self.task_list_manager = TelegramTaskListManager(
            self.task_list,
            [],
            self.heuristics,
            self.filters,
            self.statistics_service
        )

    def test__filter_urgent_tasks_with_additional_tasks(self):
        date = MagicMock()
        date.__add__.side_effect = lambda x: date
        date.__radd__ = date.__add__
        (date + TimeAmount("1d") + TimeAmount("-1s")).as_int.return_value = 2500
        # Patch getDue().as_int() to return unique ints for each task
        self.task1.getDue.return_value.as_int.return_value = 2000
        self.task2.getDue.return_value.as_int.return_value = 3000
        self.task3.getDue.return_value.as_int.return_value = 4000
        result = self.task_list_manager._TelegramTaskListManager__filter_urgent_tasks(date)
        self.assertIn(self.task1, result)
        self.assertNotIn(self.task2, result)
        self.assertNotIn(self.task3, result)

    def test__filter_and_sort_future_tasks_with_additional_tasks(self):
        date = MagicMock()
        date.__add__.side_effect = lambda x: date
        date.__radd__ = date.__add__
        (date + TimeAmount("1d") + TimeAmount("-1s")).as_int.return_value = 3000
        TimePoint.now = staticmethod(lambda: MagicMock(as_int=MagicMock(return_value=1000)))
        # Patch getStart().as_int() to return unique, sortable ints
        self.task1.getStart.return_value.as_int.return_value = 500
        self.task2.getStart.return_value.as_int.return_value = 1500
        self.task3.getStart.return_value.as_int.return_value = 2500
        result = self.task_list_manager._TelegramTaskListManager__filter_and_sort_future_tasks(self.task_list, date)
        self.assertIn(self.task3, result)
        self.assertIn(self.task2, result)
        self.assertNotIn(self.task1, result)


if __name__ == '__main__':
    unittest.main()
