import unittest
from unittest.mock import MagicMock, patch
from src.heuristics.CfdHeuristic import CfdHeuristic
from src.wrappers.TimeManagement import TimeAmount, TimePoint
import datetime


class TestCfdHeuristic(unittest.TestCase):

    def setUp(self):
        self.dedication = TimeAmount("4p")  # 4 pomodoros per day
        self.heuristic = CfdHeuristic(self.dedication)

        # Fix "today" to a known timestamp for deterministic tests
        self.fixed_today = TimePoint(datetime.datetime(2026, 1, 15, 0, 0, 0))
        self.today_patcher = patch(
            "src.heuristics.CfdHeuristic.TimePoint.today",
            return_value=self.fixed_today,
        )
        self.mock_today = self.today_patcher.start()

    def tearDown(self):
        self.today_patcher.stop()

    def _make_task(
        self,
        severity: float,
        total_cost_str: str,
        invested_effort_str: str,
        start: TimePoint,
    ) -> MagicMock:
        task = MagicMock()
        task.getSeverity.return_value = severity
        task.getTotalCost.return_value = TimeAmount(total_cost_str)
        task.getInvestedEffort.return_value = TimeAmount(invested_effort_str)
        task.getStart.return_value = start
        return task

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def test_init(self):
        self.assertEqual(self.heuristic.dedication, self.dedication)
        self.assertEqual(self.heuristic.daysOffset, 0)

    def test_init_with_days_offset(self):
        h = CfdHeuristic(self.dedication, daysOffset=3)
        self.assertEqual(h.daysOffset, 3)

    # ------------------------------------------------------------------
    # evaluate / fastEvaluate
    # ------------------------------------------------------------------

    def test_evaluate_basic(self):
        """
        Manual calculation with fixed values:
        - dedication = 4p  → ppd = 4.0
        - severity = 2
        - investedEffort = 5p → 5.0 pomodoros
        - start = 2026-01-05 00:00  (10 days before fixed_today)
        - daysActive = TimeAmount("{today_ts - start_ts}s").as_days()
          today_ts = 1736899200.0, start_ts = 1736035200.0
          diff = 864000 seconds
          TimeAmount("864000s").as_days() → 864000*1000 / 86400000 = 10
        - period = TimeAmount(f"{2 / 4}p").as_pomodoros()
                 = TimeAmount("0.5p") → 750000ms → ceil(750000*25 / 1500000)/25
                 = ceil(12.5)/25 = 13/25 = 0.52
        - divisor = 1 + 10 / 0.52 ≈ 20.2308
        - result = 5.0 / 20.2308 ≈ 0.2471
        """
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        task = self._make_task(
            severity=2, total_cost_str="10p", invested_effort_str="5p", start=start
        )

        period = TimeAmount(f"{2 / 4}p").as_pomodoros()
        divisor = 1 + 10 / period
        expected = 5.0 / divisor

        result = self.heuristic.evaluate(task)
        self.assertAlmostEqual(result, expected, places=4)

    def test_fast_evaluate_same_as_evaluate(self):
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        task = self._make_task(
            severity=2, total_cost_str="10p", invested_effort_str="5p", start=start
        )

        ppd = self.dedication.as_pomodoros()
        fast_result = self.heuristic.fastEvaluate(task, ppd)
        eval_result = self.heuristic.evaluate(task)
        self.assertAlmostEqual(fast_result, eval_result, places=5)

    def test_evaluate_zero_invested_effort(self):
        """When no effort has been invested the score should be 0."""
        start = TimePoint(datetime.datetime(2026, 1, 10, 0, 0, 0))
        task = self._make_task(
            severity=1, total_cost_str="8p", invested_effort_str="0p", start=start
        )

        result = self.heuristic.evaluate(task)
        self.assertEqual(result, 0.0)

    def test_evaluate_high_severity(self):
        """
        Higher severity increases the period, reducing the divisor for the
        same daysActive and thus yielding a higher score.
        """
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        task_low = self._make_task(
            severity=1, total_cost_str="10p", invested_effort_str="5p", start=start
        )
        task_high = self._make_task(
            severity=4, total_cost_str="10p", invested_effort_str="5p", start=start
        )

        score_low = self.heuristic.evaluate(task_low)
        score_high = self.heuristic.evaluate(task_high)
        self.assertGreater(score_high, score_low)

    def test_evaluate_recently_started_task(self):
        """
        Task started same day as today → daysActive = 0
        divisor = 1 + 0/period = 1
        score = investedEffort pomodoros
        """
        start = TimePoint(datetime.datetime(2026, 1, 15, 0, 0, 0))
        task = self._make_task(
            severity=2, total_cost_str="8p", invested_effort_str="3p", start=start
        )

        result = self.heuristic.evaluate(task)
        expected = TimeAmount("3p").as_pomodoros()  # 3.0
        self.assertAlmostEqual(result, expected, places=2)

    # ------------------------------------------------------------------
    # sort
    # ------------------------------------------------------------------

    def test_sort_returns_tuples(self):
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        tasks = [
            self._make_task(2, "10p", "5p", start),
            self._make_task(1, "8p", "2p", start),
        ]

        sorted_tasks = self.heuristic.sort(tasks)
        self.assertEqual(len(sorted_tasks), 2)
        self.assertTrue(
            all(isinstance(item, tuple) and len(item) == 2 for item in sorted_tasks)
        )

    def test_sort_ascending_order(self):
        """sort() should return tasks in ascending score order (lowest first)."""
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        task_a = self._make_task(2, "10p", "1p", start)
        task_b = self._make_task(2, "10p", "8p", start)

        sorted_tasks = self.heuristic.sort([task_b, task_a])
        self.assertLessEqual(sorted_tasks[0][1], sorted_tasks[1][1])

    def test_sort_all_tasks_present(self):
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        t1 = self._make_task(1, "4p", "1p", start)
        t2 = self._make_task(2, "8p", "3p", start)
        t3 = self._make_task(3, "12p", "6p", start)

        sorted_tasks = self.heuristic.sort([t1, t2, t3])
        task_objects = [item[0] for item in sorted_tasks]
        self.assertIn(t1, task_objects)
        self.assertIn(t2, task_objects)
        self.assertIn(t3, task_objects)

    # ------------------------------------------------------------------
    # getComment
    # ------------------------------------------------------------------

    def test_get_comment(self):
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        task = self._make_task(
            severity=2, total_cost_str="10p", invested_effort_str="5p", start=start
        )

        comment = self.heuristic.getComment(task)
        expected_value = round(self.heuristic.evaluate(task), 2)
        self.assertEqual(comment, str(expected_value))

    # ------------------------------------------------------------------
    # getDescription
    # ------------------------------------------------------------------

    def test_get_description(self):
        description = self.heuristic.getDescription()
        self.assertIsInstance(description, str)
        self.assertIn("CFD", description)

    # ------------------------------------------------------------------
    # Edge cases / different dedication values
    # ------------------------------------------------------------------

    def test_different_dedication(self):
        """Using a smaller dedication increases period and decreases divisor."""
        start = TimePoint(datetime.datetime(2026, 1, 5, 0, 0, 0))
        task = self._make_task(
            severity=2, total_cost_str="10p", invested_effort_str="5p", start=start
        )

        h2 = CfdHeuristic(TimeAmount("2p"))
        score_lower_ded = h2.evaluate(task)

        h8 = CfdHeuristic(TimeAmount("8p"))
        score_higher_ded = h8.evaluate(task)

        # Lower dedication → larger period → smaller divisor → higher score
        self.assertGreater(score_lower_ded, score_higher_ded)

    def test_single_task_sort(self):
        start = TimePoint(datetime.datetime(2026, 1, 10, 0, 0, 0))
        task = self._make_task(1, "4p", "2p", start)

        sorted_tasks = self.heuristic.sort([task])
        self.assertEqual(len(sorted_tasks), 1)
        self.assertIs(sorted_tasks[0][0], task)

    def test_empty_task_list_sort(self):
        sorted_tasks = self.heuristic.sort([])
        self.assertEqual(sorted_tasks, [])


if __name__ == "__main__":
    unittest.main()
