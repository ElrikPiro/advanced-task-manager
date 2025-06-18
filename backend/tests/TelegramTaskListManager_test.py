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

    def test__filter_high_heuristic_tasks(self):
        urgent_tasks = [self.task1]
        # Patch getStatus for all tasks
        self.task1.getStatus.return_value = ""
        self.task2.getStatus.return_value = ""
        self.task3.getStatus.return_value = ""
        result = self.task_list_manager._TelegramTaskListManager__filter_high_heuristic_tasks(urgent_tasks)
        self.assertIn(self.task3, result)
        self.assertIn(self.task2, result)
        self.assertNotIn(self.task1, result)

    def test__render_other_tasks(self):
        TelegramTaskListManager.render_task_list_str = MagicMock(return_value="other tasks list")
        agenda_str = "Agenda: "
        other_tasks = [self.task3]
        result = self.task_list_manager._TelegramTaskListManager__render_other_tasks(agenda_str, other_tasks)
        self.assertIn("# Other tasks:", result)
        self.assertIn("other tasks list", result)

    def test_render_task_information_basic(self):
        # Arrange
        task = MagicMock()
        task.getDescription.return_value = "Test Task"
        task.getContext.return_value = "Test Context"
        task.getSeverity.return_value = "High"
        task.getStart.return_value = "2025-05-28"
        task.getDue.return_value = "2025-06-01"
        task.getTotalCost.return_value.as_pomodoros.return_value = 3.0
        task.getInvestedEffort.return_value.as_pomodoros.return_value = 2.0
        task.getTotalCost.return_value = MagicMock(as_pomodoros=MagicMock(return_value=3.0))
        task.getInvestedEffort.return_value = MagicMock(as_pomodoros=MagicMock(return_value=2.0))
        taskProvider = MagicMock()
        taskProvider.getTaskMetadata.return_value = "meta"
        self.task_list_manager._TelegramTaskListManager__heuristicList = []
        # Act
        result = self.task_list_manager.render_task_information(task, taskProvider, extended=False)
        # Assert
        self.assertIn("Task: Test Task", result)
        self.assertIn("Context: Test Context", result)
        self.assertIn("Start Date: 2025-05-28", result)
        self.assertIn("Due Date: 2025-06-01", result)
        self.assertIn("Total Cost:", result)
        self.assertIn("Remaining:", result)
        self.assertIn("Severity: High", result)
        self.assertIn("/list - Return to list", result)
        self.assertIn("/done - Mark task as done", result)
        self.assertIn("/set [param] [value] - Set task parameter", result)
        self.assertIn("/work [work_units] - invest work units in the task", result)
        self.assertIn("/snooze - snooze the task for 5 minutes", result)
        self.assertIn("/info - Show extended information", result)

    def test_render_task_information_extended(self):
        # Arrange
        task = MagicMock()
        task.getDescription.return_value = "Test Task"
        task.getContext.return_value = "Test Context"
        task.getSeverity.return_value = "High"
        task.getStart.return_value = "2025-05-28"
        task.getDue.return_value = "2025-06-01"
        task.getTotalCost.return_value.as_pomodoros.return_value = 3.0
        task.getInvestedEffort.return_value.as_pomodoros.return_value = 2.0
        task.getTotalCost.return_value = MagicMock(as_pomodoros=MagicMock(return_value=3.0))
        task.getInvestedEffort.return_value = MagicMock(as_pomodoros=MagicMock(return_value=2.0))
        taskProvider = MagicMock()
        taskProvider.getTaskMetadata.return_value = "meta"
        heuristic = MagicMock()
        heuristic.getComment.return_value = "Heuristic comment"
        self.task_list_manager._TelegramTaskListManager__heuristicList = [("Priority", heuristic)]
        # Act
        result = self.task_list_manager.render_task_information(task, taskProvider, extended=True)
        # Assert
        self.assertIn("Task: Test Task", result)
        self.assertIn("Context: Test Context", result)
        self.assertIn("Start Date: 2025-05-28", result)
        self.assertIn("Due Date: 2025-06-01", result)
        self.assertIn("Total Cost:", result)
        self.assertIn("Remaining:", result)
        self.assertIn("Severity: High", result)
        self.assertIn("Priority: Heuristic comment", result)
        self.assertIn("<b>Metadata:</b><code>meta</code>", result)
        self.assertIn("/list - Return to list", result)
        self.assertIn("/done - Mark task as done", result)
        self.assertIn("/set [param] [value] - Set task parameter", result)
        self.assertIn("/work [work_units] - invest work units in the task", result)
        self.assertIn("/snooze - snooze the task for 5 minutes", result)
        self.assertIn("/info - Show extended information", result)

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

    def test_get_list_stats_with_additional_tasks(self):
        # Arrange
        # Set up getWorkDone to return different values for different dates
        work_done_values = {
            0: TimeAmount("1p"),
            1: TimeAmount("2p"),
            2: TimeAmount("0p"),
            3: TimeAmount("3p"),
            4: TimeAmount("1.5p"),
            5: TimeAmount("2.5p"),
            6: TimeAmount("4p")
        }

        def mock_get_work_done(date):
            today = TimePoint.today()
            for i in range(7):
                if (today + TimeAmount(f"-{i}d")).as_int() == date.as_int():
                    return work_done_values.get(i, TimeAmount("0p"))
            return TimeAmount("0p")

        self.statistics_service.getWorkDone.side_effect = mock_get_work_done

        # Set up getWorkloadStats to return predefined values
        workload_stats = (
            "2.0p",  # workload
            "10p",   # remaining effort
            "0.8",   # heuristic value
            "Urgency",  # heuristic name
            "Task 1",   # offender
            "1.5p"      # offenderMax
        )
        self.statistics_service.getWorkloadStats.return_value = workload_stats

        # Set up getWorkDoneLog to return a sample log with valid ms timestamps
        import time
        now_ms = int(time.time() * 1000)
        work_done_log = [
            {"task": "Task 1", "work_units": "1", "timestamp": now_ms},
            {"task": "Task 2", "work_units": "2", "timestamp": now_ms - 3600000},
            {"task": "Task 3", "work_units": "3", "timestamp": now_ms - 7200000}
        ]
        self.statistics_service.getWorkDoneLog.return_value = work_done_log

        # Act
        result = self.task_list_manager.get_list_stats()

        # Assert
        self.assertIn("Work done in the last 7 days:", result)
        self.assertIn("|    Date    | Work  Done |", result)
        # Check for the average work done (1 + 2 + 0 + 3 + 1.5 + 2.5 + 4) / 7 = 2.0 (rounded)
        self.assertIn("|   Average  |    2.0    |", result)
        self.assertIn("Workload statistics:", result)
        self.assertIn("current workload: 2.0p per day", result)
        self.assertIn("max Offender: 'Task 1' with 1.5p per day", result)
        self.assertIn("total remaining effort: 10p", result)
        self.assertIn("max Urgency: 0.8", result)
        self.assertIn("Work done log:", result)
        for entry in work_done_log:
            task = entry["task"]
            work_units = entry["work_units"]
            timeAmount = TimeAmount(f"{work_units}p")
            self.assertIn(f"{timeAmount} on {task}", result)
        self.assertIn("/list - return back to the task list", result)
        self.assertEqual(self.statistics_service.getWorkDone.call_count, 7)
        self.statistics_service.getWorkloadStats.assert_called_once_with(self.task_list)
        self.statistics_service.getWorkDoneLog.assert_called_once()

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

    def test__filter_high_heuristic_tasks_with_additional_tasks(self):
        urgent_tasks = [self.task1]
        self.task1.getStatus.return_value = ""
        self.task2.getStatus.return_value = ""
        self.task3.getStatus.return_value = ""
        result = self.task_list_manager._TelegramTaskListManager__filter_high_heuristic_tasks(urgent_tasks)
        self.assertIn(self.task3, result)
        self.assertIn(self.task2, result)
        self.assertNotIn(self.task1, result)

    def test__render_other_tasks_with_additional_tasks(self):
        TelegramTaskListManager.render_task_list_str = MagicMock(return_value="other tasks list")
        agenda_str = "Agenda: "
        other_tasks = [self.task3]
        result = self.task_list_manager._TelegramTaskListManager__render_other_tasks(agenda_str, other_tasks)
        self.assertIn("# Other tasks:", result)
        self.assertIn("other tasks list", result)


if __name__ == '__main__':
    unittest.main()
