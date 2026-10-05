"""Concurrency and receipt behavior for the mutation coordinator."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from collections.abc import Callable
from uuid import uuid4

from src.AtomicFileStore import AtomicWriteError
from src.MutationCoordinator import (
    MutationCoordinator,
    OperationIdConflict,
    OperationResultUnavailable,
)


class MutationCoordinatorTest(unittest.TestCase):

    def setUp(self) -> None:
        self.coordinator = MutationCoordinator()

    def tearDown(self) -> None:
        self.coordinator.close()

    @staticmethod
    def _wait_until(
        predicate: Callable[[], bool], timeout: float = 2.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.001)
        raise AssertionError("condition was not met before timeout")

    @staticmethod
    def _thread_call(
        callable_: Callable[[], object],
        results: list[object],
        errors: list[BaseException],
    ) -> None:
        try:
            results.append(callable_())
        except BaseException as error:
            errors.append(error)

    def test_jobs_run_in_fifo_order_across_calling_threads(self) -> None:
        first_started = threading.Event()
        release_first = threading.Event()
        order: list[str] = []
        first_results: list[object] = []
        second_results: list[object] = []
        errors: list[BaseException] = []

        def first_job() -> str:
            order.append("first-start")
            first_started.set()
            self.assertTrue(release_first.wait(2))
            order.append("first-end")
            return "first"

        def second_job() -> str:
            order.append("second")
            return "second"

        first_thread = threading.Thread(
            target=self._thread_call,
            args=(
                lambda: self.coordinator.run_job(first_job),
                first_results,
                errors,
            ),
        )
        first_thread.start()
        self.assertTrue(first_started.wait(2))

        second_thread = threading.Thread(
            target=self._thread_call,
            args=(
                lambda: self.coordinator.run_job(second_job),
                second_results,
                errors,
            ),
        )
        second_thread.start()
        self._wait_until(lambda: self.coordinator._queue.qsize() == 1)
        self.assertEqual(["first-start"], order)

        release_first.set()
        first_thread.join(2)
        second_thread.join(2)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(["first-start", "first-end", "second"], order)
        self.assertEqual(["first"], first_results)
        self.assertEqual(["second"], second_results)

    def test_reentrant_internal_job_runs_inline(self) -> None:
        order: list[str] = []

        def outer_job() -> str:
            order.append("outer-before")
            result = self.coordinator.run_or_inline(
                lambda: order.append("nested") or "done"
            )
            order.append("outer-after")
            return result

        self.assertEqual("done", self.coordinator.run_job(outer_job))
        self.assertEqual(["outer-before", "nested", "outer-after"], order)

    def test_same_operation_waits_and_returns_same_result(self) -> None:
        operation_id = uuid4()
        started = threading.Event()
        release = threading.Event()
        duplicate_calling = threading.Event()
        invocations: list[object] = []
        first_results: list[object] = []
        duplicate_results: list[object] = []
        errors: list[BaseException] = []
        intent = {
            "type": "edit-task",
            "taskId": "task-1",
            "parameters": {"name": "A"},
        }

        def work(snapshot: object) -> dict[str, object]:
            invocations.append(snapshot)
            started.set()
            self.assertTrue(release.wait(2))
            return {"changed": True, "intent": snapshot}

        first_thread = threading.Thread(
            target=self._thread_call,
            args=(
                lambda: self.coordinator.run_operation(
                    operation_id,
                    intent,
                    work,
                ),
                first_results,
                errors,
            ),
        )
        first_thread.start()
        self.assertTrue(started.wait(2))

        def duplicate() -> object:
            duplicate_calling.set()
            return self.coordinator.run_operation(operation_id, intent, work)

        duplicate_thread = threading.Thread(
            target=self._thread_call,
            args=(duplicate, duplicate_results, errors),
        )
        duplicate_thread.start()
        self.assertTrue(duplicate_calling.wait(2))
        self.assertFalse(duplicate_results)

        with self.assertRaises(OperationIdConflict):
            self.coordinator.run_operation(
                operation_id,
                {
                    "type": "edit-task",
                    "taskId": "task-1",
                    "parameters": {"name": "B"},
                },
                work,
            )

        release.set()
        first_thread.join(2)
        duplicate_thread.join(2)
        self.assertEqual([], errors)
        self.assertEqual(1, len(invocations))
        self.assertEqual(first_results, duplicate_results)
        receipt = self.coordinator.get_receipt(operation_id)
        self.assertEqual("succeeded", receipt.status)
        self.assertEqual(first_results[0], receipt.result)

    def test_receipt_and_callback_snapshot_mutable_data(self) -> None:
        operation_id = uuid4()
        intent: dict[str, object] = {"values": ["admitted"]}
        started = threading.Event()
        release = threading.Event()
        results: list[object] = []
        errors: list[BaseException] = []
        callback_count = 0

        def work(snapshot: object) -> dict[str, object]:
            nonlocal callback_count
            callback_count += 1
            started.set()
            self.assertTrue(release.wait(2))
            return {"observed": snapshot}

        caller = threading.Thread(
            target=self._thread_call,
            args=(
                lambda: self.coordinator.run_operation(
                    operation_id,
                    intent,
                    work,
                ),
                results,
                errors,
            ),
        )
        caller.start()
        self.assertTrue(started.wait(2))
        intent["values"] = ["changed after admission"]
        release.set()
        caller.join(2)
        self.assertEqual([], errors)

        result = results[0]
        self.assertEqual({"observed": {"values": ["admitted"]}}, result)
        result["observed"]["values"].append(
            "mutated returned copy"  # type: ignore[index]
        )

        receipt = self.coordinator.get_receipt(operation_id)
        self.assertEqual({"values": ["admitted"]}, receipt.intent)
        self.assertEqual(
            {"observed": {"values": ["admitted"]}},
            receipt.result,
        )
        receipt.result["observed"]["values"].append(
            "mutated receipt copy"  # type: ignore[index]
        )
        self.assertEqual(
            {"observed": {"values": ["admitted"]}},
            self.coordinator.get_receipt(operation_id).result,
        )
        self.assertEqual(1, callback_count)

    def test_receipt_retention_excludes_inflight_operations(self) -> None:
        outer_id = uuid4()
        child_ids: list[object] = []
        during_turn: list[object] = []

        def outer_work(_: object) -> str:
            for index in range(self.coordinator.RECEIPT_LIMIT + 1):
                child_id = uuid4()
                child_ids.append(child_id)
                self.coordinator.run_operation(
                    child_id,
                    {"index": index},
                    lambda snapshot: snapshot,
                )

            outer_receipt = self.coordinator.get_receipt(outer_id)
            during_turn.append(outer_receipt.status)
            with self.assertRaises(OperationResultUnavailable):
                self.coordinator.get_receipt(child_ids[0])
            child_receipt = self.coordinator.get_receipt(child_ids[1])
            self.assertEqual("succeeded", child_receipt.status)
            return "finished"

        self.assertEqual(
            "finished",
            self.coordinator.run_operation(
                outer_id,
                {"type": "outer"},
                outer_work,
            ),
        )
        self.assertEqual(["running"], during_turn)
        outer_receipt = self.coordinator.get_receipt(outer_id)
        self.assertEqual("succeeded", outer_receipt.status)
        with self.assertRaises(OperationResultUnavailable):
            self.coordinator.get_receipt(child_ids[1])
        self.assertEqual(
            "succeeded",
            self.coordinator.get_receipt(child_ids[2]).status,
        )
        self.assertEqual(
            "succeeded",
            self.coordinator.get_receipt(child_ids[-1]).status,
        )

    def test_failure_is_retained_and_the_next_job_still_runs(self) -> None:
        class PartialFailure(RuntimeError):
            effects_state = "partial"

        failed_id = uuid4()
        ran: list[bool] = []

        def fail(_: object) -> None:
            raise PartialFailure("first destination was saved")

        with self.assertRaises(PartialFailure):
            self.coordinator.run_operation(failed_id, {"type": "save"}, fail)

        receipt = self.coordinator.get_receipt(failed_id)
        self.assertEqual("failed", receipt.status)
        self.assertIsNotNone(receipt.failure)
        self.assertEqual(
            "partial",
            receipt.failure.effects_state,  # type: ignore[union-attr]
        )
        self.assertEqual(
            "next",
            self.coordinator.run_job(lambda: ran.append(True) or "next"),
        )
        self.assertEqual([True], ran)

    def test_failure_details_are_isolated_between_callers(self) -> None:
        class DetailedFailure(RuntimeError):
            code = "operation-failed"
            effects_state = "partial"

            def __init__(self) -> None:
                super().__init__("one file was saved")
                self.details = {"saved_count": "1", "saved_ids": '["task-1"]'}

        operation_id = uuid4()
        calls: list[bool] = []
        raised: list[DetailedFailure] = []

        def fail(_: object) -> None:
            calls.append(True)
            error = DetailedFailure()
            raised.append(error)
            raise error

        with self.assertRaises(DetailedFailure) as first:
            self.coordinator.run_operation(
                operation_id,
                {"type": "save-many"},
                fail,
            )
        first.exception.details["saved_ids"] = "mutated by the first caller"
        raised[0].details["saved_count"] = "mutated by the callback owner"

        with self.assertRaises(DetailedFailure) as duplicate:
            self.coordinator.run_operation(
                operation_id,
                {"type": "save-many"},
                lambda _: self.fail("duplicate callback was run"),
            )

        self.assertEqual(1, len(calls))
        self.assertEqual(
            '["task-1"]',
            duplicate.exception.details["saved_ids"],
        )
        receipt = self.coordinator.get_receipt(operation_id)
        self.assertEqual(
            "operation-failed",
            receipt.failure.code,  # type: ignore[union-attr]
        )
        self.assertEqual(
            "partial",
            receipt.failure.effects_state,  # type: ignore[union-attr]
        )
        self.assertEqual(
            "1",
            receipt.failure.details["saved_count"],  # type: ignore[union-attr]
        )
        self.assertEqual(
            '["task-1"]',
            receipt.failure.details["saved_ids"],  # type: ignore[union-attr]
        )

    def test_write_failure_retains_phase_and_effect_evidence(self) -> None:
        operation_id = uuid4()

        def fail(_: object) -> None:
            raise AtomicWriteError(
                "/data/tasks.json",
                "directory_fsync",
                "unknown",
                None,
                OSError("directory sync failed"),
            )

        with self.assertRaises(AtomicWriteError):
            self.coordinator.run_operation(
                operation_id,
                {"type": "save"},
                fail,
            )

        failure = self.coordinator.get_receipt(operation_id).failure
        self.assertIsNotNone(failure)
        self.assertEqual(
            "unknown",
            failure.effects_state,  # type: ignore[union-attr]
        )
        self.assertEqual(
            "/data/tasks.json",
            failure.context["path"],  # type: ignore[union-attr]
        )
        self.assertEqual(
            "directory_fsync",
            failure.context["phase"],  # type: ignore[union-attr]
        )
        self.assertIsNone(
            failure.context["replaced"]  # type: ignore[union-attr]
        )

    def test_get_missing_or_restarted_receipt_never_replays_work(self) -> None:
        operation_id = uuid4()
        invocations: list[bool] = []
        self.coordinator.run_operation(
            operation_id,
            {"type": "once"},
            lambda _: invocations.append(True) or {"saved": True},
        )
        self.coordinator.close()

        restarted = MutationCoordinator()
        try:
            with self.assertRaises(OperationResultUnavailable):
                restarted.get_receipt(operation_id)
            with self.assertRaises(OperationResultUnavailable):
                restarted.get_receipt(uuid4())
            self.assertEqual([True], invocations)
        finally:
            restarted.close()

    def test_cancelled_async_waiter_does_not_cancel_job(self) -> None:
        operation_id = uuid4()
        started = threading.Event()
        release = threading.Event()
        invocations: list[bool] = []

        def work(_: object) -> str:
            invocations.append(True)
            started.set()
            self.assertTrue(release.wait(2))
            return "completed"

        async def scenario() -> None:
            waiter = asyncio.create_task(
                self.coordinator.run_operation_async(
                    operation_id,
                    {"type": "async"},
                    work,
                )
            )
            deadline = asyncio.get_running_loop().time() + 2
            while (
                not started.is_set()
                and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.001)
            self.assertTrue(started.is_set())
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            release.set()
            await self.coordinator.run_job_async(lambda: None)

        asyncio.run(scenario())
        self.assertEqual([True], invocations)
        receipt = self.coordinator.get_receipt(operation_id)
        self.assertEqual("succeeded", receipt.status)
        self.assertEqual(
            "completed",
            self.coordinator.run_operation(
                operation_id,
                {"type": "async"},
                lambda _: self.fail("duplicate operation was replayed"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
