import datetime
import os
import time
import unittest
from unittest.mock import MagicMock, patch
from src.TelegramTaskListManager import TelegramTaskListManager
from src.filters.ActiveTaskFilter import ActiveTaskFilter
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.heuristics.StartTimeHeuristic import StartTimeHeuristic
from src.taskmodels.TaskModel import TaskModel
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
        self.task1.getCalm.return_value = False
        self.task1.getEventWaited.return_value = None

        self.task2 = MagicMock()
        self.task2.getDescription.return_value = "Task 2"
        self.task2.getStatus.return_value = ""
        self.task2.getContext.return_value = "catB:bar"
        self.task2.getDue.return_value = MagicMock(as_int=MagicMock(return_value=3000))
        self.task2.getStart.return_value = MagicMock(as_int=MagicMock(return_value=1500))
        self.task2.getCalm.return_value = False
        self.task2.getEventWaited.return_value = None

        self.task3 = MagicMock()
        self.task3.getDescription.return_value = "Task 3"
        self.task3.getStatus.return_value = ""
        self.task3.getContext.return_value = "catA:baz"
        self.task3.getDue.return_value = MagicMock(as_int=MagicMock(return_value=4000))
        self.task3.getStart.return_value = MagicMock(as_int=MagicMock(return_value=2500))
        self.task3.getCalm.return_value = False
        self.task3.getEventWaited.return_value = None

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

    def _builtin_task_models(self):
        due = int(datetime.datetime(2026, 10, 7, 0, 0).timestamp() * 1000)
        tasks = []
        for index in range(3):
            start = int(datetime.datetime(2026, 10, 6, 9 + index, 0).timestamp() * 1000)
            tasks.append(
                TaskModel(
                    f"Built-in task {index}",
                    "work:test",
                    start,
                    due,
                    1.0,
                    4.0,
                    0.0,
                    " ",
                    "false",
                    "",
                    index,
                    None,
                    None,
                    f"builtin-{index}",
                )
            )
        return tasks

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
        # Patch getStart().as_int() to return unique, sortable ints
        self.task1.getStart.return_value.as_int.return_value = 500
        self.task2.getStart.return_value.as_int.return_value = 1500
        self.task3.getStart.return_value.as_int.return_value = 2500
        with patch.object(
            TimePoint,
            "now",
            return_value=MagicMock(as_int=MagicMock(return_value=1000)),
        ):
            result = self.task_list_manager._TelegramTaskListManager__filter_and_sort_future_tasks(
                self.task_list,
                date,
            )
        self.assertIn(self.task3, result)
        self.assertIn(self.task2, result)
        self.assertNotIn(self.task1, result)

    def test_filtered_task_list_with_active_filter(self):
        # Only task1 passes the filter
        seen_inputs = []

        class Filter:
            def filter(self_inner, tasks):
                seen_inputs.append(tasks)
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
        self.assertEqual(len(seen_inputs), len(self.task_list))
        self.assertTrue(all(len(tasks) == 1 for tasks in seen_inputs))

    def test_builtin_active_filter_batches_the_source_with_one_query_clock(self):
        current = TimePoint(datetime.datetime(2026, 10, 6, 12, 0))
        tasks = self._builtin_task_models()

        manager = TelegramTaskListManager(
            tasks,
            [],
            [],
            [("Active", ActiveTaskFilter(), True)],
            self.statistics_service,
        )
        calls = []
        original_filter_at = ActiveTaskFilter.filter_at

        def capture_filter_at(filter_instance, tasks, now):
            calls.append((tasks, now))
            return original_filter_at(filter_instance, tasks, now)

        with patch.object(ActiveTaskFilter, "filter_at", new=capture_filter_at), patch.object(
            TimePoint, "now", return_value=current
        ):
            result = manager.filtered_task_list

        self.assertEqual(result, tasks)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], tasks)
        self.assertIs(calls[0][1], current)

    def test_builtin_sorted_scores_are_reused_for_page_rows(self):
        heuristic = StartTimeHeuristic()
        tasks = self._builtin_task_models()
        evaluate_calls = []
        original_evaluate = StartTimeHeuristic.evaluate

        def capture_evaluate(heuristic_instance, task):
            evaluate_calls.append(task)
            return original_evaluate(heuristic_instance, task)

        manager = TelegramTaskListManager(
            tasks,
            [("EDF", EdfAlgorithm())],
            [("Start", heuristic)],
            [],
            self.statistics_service,
            tasksPerPage=2,
        )
        with patch.object(StartTimeHeuristic, "evaluate", new=capture_evaluate):
            content = manager.get_task_list_content()

        self.assertEqual(len(content.tasks), 2)
        self.assertEqual(len(evaluate_calls), len(tasks))

    def test_custom_sorted_scores_keep_legacy_page_reevaluation(self):
        evaluate_calls = []

        class CustomStartTimeHeuristic(StartTimeHeuristic):
            def evaluate(self_inner, task):
                evaluate_calls.append(task)
                return super().evaluate(task)

        manager = TelegramTaskListManager(
            self.task_list,
            [("EDF", EdfAlgorithm())],
            [("Custom Start", CustomStartTimeHeuristic())],
            [],
            self.statistics_service,
            tasksPerPage=2,
        )
        content = manager.get_task_list_content()

        self.assertEqual(len(content.tasks), 2)
        self.assertEqual(len(evaluate_calls), len(self.task_list) + 2)

    def test_custom_model_and_filter_keep_legacy_getter_order(self):
        getter_calls = []
        filter_inputs = []
        filter_at_calls = []
        evaluate_calls = []

        class CustomTaskModel(TaskModel):
            def getStart(self):
                getter_calls.append(self.getTaskUID())
                return super().getStart()

        class CustomActiveFilter(ActiveTaskFilter):
            def filter(self_inner, tasks):
                filter_inputs.append(tasks)
                return super().filter(tasks)

            def filter_at(self_inner, tasks, now):
                filter_at_calls.append((tasks, now))
                return super().filter_at(tasks, now)

        class CustomStartHeuristic(StartTimeHeuristic):
            def evaluate(self_inner, task):
                evaluate_calls.append(task)
                return super().evaluate(task)

        start = int(datetime.datetime(2026, 10, 6, 11, 0).timestamp() * 1000)
        due = int(datetime.datetime(2026, 10, 7, 0, 0).timestamp() * 1000)
        tasks = [
            CustomTaskModel(
                f"Custom {index}",
                "work:test",
                start,
                due,
                1.0,
                4.0,
                0.0,
                " ",
                "false",
                "",
                index,
                None,
                None,
                f"custom-{index}",
            )
            for index in range(2)
        ]
        manager = TelegramTaskListManager(
            tasks,
            [],
            [("Custom start", CustomStartHeuristic())],
            [("Custom active", CustomActiveFilter(), True)],
            self.statistics_service,
            tasksPerPage=2,
        )
        fixed_now = TimePoint(datetime.datetime(2026, 10, 6, 12, 0))

        with patch.object(TimePoint, "now", return_value=fixed_now):
            content = manager.get_task_list_content()

        self.assertEqual(len(content.tasks), 2)
        self.assertEqual(filter_inputs, [[tasks[0]], [tasks[1]]])
        self.assertEqual(filter_at_calls, [])
        self.assertEqual(
            getter_calls,
            [
                "custom-0",
                "custom-1",  # custom filter calls
                "custom-0",
                "custom-1",  # heuristic sort
                "custom-0",
                "custom-0",  # page score and resource start
                "custom-1",
                "custom-1",
            ],
        )
        self.assertEqual(len(evaluate_calls), 4)

    def test_agenda_other_tasks_use_civil_midnight_across_dst_changes(self):
        previous_timezone = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        try:
            cases = (
                (
                    datetime.datetime(2026, 3, 28, 23, 59, 59),
                    datetime.datetime(2026, 3, 29, 0, 0),
                    datetime.datetime(2026, 3, 27, 12, 0),
                ),
                (
                    datetime.datetime(2026, 10, 24, 23, 59, 59),
                    datetime.datetime(2026, 10, 25, 0, 0),
                    datetime.datetime(2026, 10, 23, 12, 0),
                ),
            )
            for now_value, due_value, agenda_day in cases:
                with self.subTest(now=now_value.isoformat()):
                    task = TaskModel(
                        "DST boundary task",
                        "work:test",
                        int((now_value - datetime.timedelta(hours=2)).timestamp() * 1000),
                        int(due_value.timestamp() * 1000),
                        1.0,
                        4.0,
                        0.0,
                        " ",
                        "false",
                        "",
                        0,
                        None,
                        None,
                        "dst-boundary",
                    )
                    manager = TelegramTaskListManager(
                        [task],
                        [],
                        [("Start", StartTimeHeuristic())],
                        [],
                        self.statistics_service,
                    )
                    fixed_now = TimePoint(now_value)
                    with patch.object(TimePoint, "now", return_value=fixed_now):
                        agenda = manager.get_day_agenda_content(TimePoint(agenda_day), [])

                    self.assertEqual(
                        [item.id for item in agenda.other_tasks],
                        ["dst-boundary"],
                    )
        finally:
            if previous_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_timezone
            time.tzset()

    def test_active_filter_uses_one_clock_value_for_a_projection(self):
        current = TimePoint(datetime.datetime(2026, 10, 6, 12, 0))
        tasks = self._builtin_task_models()
        manager = TelegramTaskListManager(
            tasks,
            [],
            [],
            [("Active", ActiveTaskFilter(), True)],
            self.statistics_service,
        )

        with patch.object(TimePoint, "now", return_value=current) as now:
            result = manager.filtered_task_list

        self.assertEqual(result, tasks)
        now.assert_called_once_with()

    def test_filtered_task_list_with_no_active_filter_is_empty_union(self):
        # No filters enabled is an empty union when a filter catalog exists.
        filters = [("Active", MagicMock(), False)]
        manager = TelegramTaskListManager(self.task_list, [], self.heuristics, filters, self.statistics_service)
        # This mock deliberately returns rows regardless of its input, so the
        # empty-union behavior must exit before strategy application.
        heuristic_mock = MagicMock()
        heuristic_mock.sort.return_value = list(reversed([(t, 0) for t in self.task_list]))
        manager._TelegramTaskListManager__heuristicList = [("Priority", heuristic_mock)]
        manager._TelegramTaskListManager__selectedHeuristic = ("Priority", heuristic_mock)
        filtered = manager.filtered_task_list
        self.assertEqual(filtered, [])
        heuristic_mock.sort.assert_not_called()


class TestTelegramTaskListManagerAdditional(unittest.TestCase):

    def setUp(self):
        # Create mock task models
        self.task1 = MagicMock()
        self.task1.getDescription.return_value = "Task 1"
        self.task1.getStatus.return_value = ""
        self.task1.getCalm.return_value = False
        self.task1.getEventWaited.return_value = None

        self.task2 = MagicMock()
        self.task2.getDescription.return_value = "Task 2"
        self.task2.getStatus.return_value = ""
        self.task2.getCalm.return_value = False
        self.task2.getEventWaited.return_value = None

        self.task3 = MagicMock()
        self.task3.getDescription.return_value = "Task 3"
        self.task3.getStatus.return_value = ""
        self.task3.getCalm.return_value = False
        self.task3.getEventWaited.return_value = None

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
        # Patch getStart().as_int() to return unique, sortable ints
        self.task1.getStart.return_value.as_int.return_value = 500
        self.task2.getStart.return_value.as_int.return_value = 1500
        self.task3.getStart.return_value.as_int.return_value = 2500
        with patch.object(
            TimePoint,
            "now",
            return_value=MagicMock(as_int=MagicMock(return_value=1000)),
        ):
            result = self.task_list_manager._TelegramTaskListManager__filter_and_sort_future_tasks(
                self.task_list,
                date,
            )
        self.assertIn(self.task3, result)
        self.assertIn(self.task2, result)
        self.assertNotIn(self.task1, result)


if __name__ == '__main__':
    unittest.main()
