import asyncio
import datetime
import os
import tempfile
import threading
import unittest
from typing import Callable
from unittest.mock import MagicMock

from src.AtomicFileStore import AtomicWriteError
from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry
from src.JsonProjectManager import JsonProjectManager
from src.MutationCoordinator import MutationCoordinator
from src.StatisticsService import StatisticsService
from src.TelegramReportingService import TelegramReportingService
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import OperationFailedError
from src.domain.models import OperationTarget
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.taskproviders.TaskProvider import TaskProvider
from src.wrappers.TimeManagement import TimeAmount, TimePoint


class MutationChannelsIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_channel_maintenance_statistics_and_project_writes_share_one_turn_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            coordinator = MutationCoordinator()
            broker = FileBroker(directory, os.path.join(directory, "appdata"), os.path.join(directory, "vault"), coordinator)
            json_provider = TaskJsonProvider(broker, mutation_coordinator=coordinator)
            task_provider = TaskProvider(
                json_provider,
                broker,
                disableThreading=True,
                mutation_coordinator=coordinator,
            )
            today = TimePoint.today().as_int()
            broker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, {
                "tasks": [{
                    "id": "task-work-1",
                    "description": "Work task",
                    "context": "inbox",
                    "start": today,
                    "due": today,
                    "severity": 1.0,
                    "totalCost": 4.0,
                    "investedEffort": 0.0,
                    "status": " ",
                    "calm": "False",
                    "raised": "ready-event",
                }],
                "projects": [],
            })

            filter_service = MagicMock()
            heuristic = MagicMock()
            stats_service = StatisticsService(
                broker,
                filter_service,
                heuristic,
                heuristic,
                mutation_coordinator=coordinator,
            )
            project_manager = JsonProjectManager(json_provider, mutation_coordinator=coordinator)
            task_list_manager = MagicMock()
            selected_task = task_provider.getTaskList()[0]
            task_list_manager.selected_task = selected_task
            application_service = TaskApplicationService(
                task_provider,
                MagicMock(),
                stats_service,
                task_list_manager,
                [{"prefix": "inbox"}],
                project_manager,
                mutation_coordinator=coordinator,
            )
            reporting_service = TelegramReportingService(
                MagicMock(),
                task_provider,
                MagicMock(),
                stats_service,
                task_list_manager,
                [{"prefix": "inbox"}],
                project_manager,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                application_service,
                mutation_coordinator=coordinator,
            )

            # Hold the worker's first turn while one operation from each path
            # reaches the same queue in a known admission order.
            condition = threading.Condition()
            admitted_items = 0
            original_put = coordinator._queue.put

            def observe_admission(item: object, *args: object, **kwargs: object) -> None:
                nonlocal admitted_items
                original_put(item, *args, **kwargs)
                if item is not None:
                    with condition:
                        admitted_items += 1
                        condition.notify_all()

            coordinator._queue.put = observe_admission  # type: ignore[method-assign]
            turn_started = threading.Event()
            release_turn = threading.Event()

            def hold_turn() -> None:
                turn_started.set()
                if not release_turn.wait(3):
                    raise TimeoutError("test did not release the coordinator turn")

            blocker = threading.Thread(target=lambda: coordinator.run_job(hold_turn))
            blocker.start()
            self.assertTrue(turn_started.wait(1))

            background_calls: list[tuple[threading.Thread, threading.Event, list[object]]] = []

            async def wait_for_admissions(expected_count: int) -> bool:
                deadline = asyncio.get_running_loop().time() + 3
                while asyncio.get_running_loop().time() < deadline:
                    with condition:
                        if admitted_items >= expected_count:
                            return True
                    await asyncio.sleep(0.01)
                return False

            def start_background_call(callback: Callable[[], object]) -> None:
                completed = threading.Event()
                outcome: list[object] = []

                def run_call() -> None:
                    try:
                        outcome.append(callback())
                    except BaseException as error:
                        outcome.append(error)
                    finally:
                        completed.set()

                worker = threading.Thread(target=run_call)
                background_calls.append((worker, completed, outcome))
                worker.start()

            try:
                channel_mutation = asyncio.create_task(
                    reporting_service.workCommand("/work 30m", expectAnswer=False)
                )
                self.assertTrue(await wait_for_admissions(2), "Telegram mutation was not admitted")
                start_background_call(task_provider.discoverTasks)
                self.assertTrue(await wait_for_admissions(3), "maintenance was not admitted")
                start_background_call(lambda: stats_service.doWork(
                    datetime.date.today(),
                    TimeAmount("1p"),
                    selected_task,
                ))
                self.assertTrue(await wait_for_admissions(4), "statistics write was not admitted")
                start_background_call(lambda: project_manager.perform_operation(
                    "open-project",
                    "Shared queue project",
                    {"description": "Created through the project service"},
                ))
                self.assertTrue(await wait_for_admissions(5), "project write was not admitted")

                self.assertFalse(channel_mutation.done())
                self.assertTrue(all(not completed.is_set() for _, completed, _ in background_calls))

                release_turn.set()
                channel_outcome = await asyncio.gather(channel_mutation, return_exceptions=True)
                outcomes: list[object] = list(channel_outcome)
                deadline = asyncio.get_running_loop().time() + 3
                while (
                    any(not completed.is_set() for _, completed, _ in background_calls)
                    and asyncio.get_running_loop().time() < deadline
                ):
                    await asyncio.sleep(0.01)
                outcomes.extend(value for _, _, result in background_calls for value in result)
                self.assertTrue(all(completed.is_set() for _, completed, _ in background_calls))
                self.assertFalse(
                    [outcome for outcome in outcomes if isinstance(outcome, BaseException)],
                    outcomes,
                )
                task_provider.discoverTasks()
            finally:
                release_turn.set()
                for worker, _, _ in background_calls:
                    worker.join(2)
                blocker.join(2)
                task_provider.dispose()
                coordinator.close(wait=True)
            self.assertFalse(blocker.is_alive())
            self.assertTrue(all(not worker.is_alive() for worker, _, _ in background_calls))

            document = broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
            self.assertTrue(any(
                project.get("name") == "Shared queue project" and project.get("status") == "open"
                for project in document["projects"]
            ))
            self.assertTrue(any(
                task.get("project") == "Shared queue project" and task.get("description") == "Define next action"
                for task in document["tasks"]
            ))
            statistics = broker.readStatisticsFileContentJson()
            expected_work = TimeAmount("30m").as_pomodoros() + TimeAmount("1p").as_pomodoros()
            self.assertAlmostEqual(statistics[datetime.date.today().isoformat()], expected_work)
            self.assertEqual(len(statistics["log"]), 2)
            refreshed_task = next(task for task in task_provider.getTaskList() if task.getTaskUID() == "task-work-1")
            self.assertAlmostEqual(refreshed_task.getInvestedEffort().as_pomodoros(), TimeAmount("30m").as_pomodoros())

    async def test_telegram_channel_admits_typed_operation_before_yielding_to_worker(self) -> None:
        # The integration above covers real channel writes; this verifies the
        # asynchronous entry point with an explicit receipt identity.
        with tempfile.TemporaryDirectory() as directory:
            coordinator = MutationCoordinator()
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"), coordinator)
            json_provider = TaskJsonProvider(broker, mutation_coordinator=coordinator)
            task_provider = TaskProvider(json_provider, broker, disableThreading=True, mutation_coordinator=coordinator)
            project_manager = JsonProjectManager(json_provider, mutation_coordinator=coordinator)
            stats_service = StatisticsService(broker, MagicMock(), MagicMock(), MagicMock(), coordinator)
            application_service = TaskApplicationService(
                task_provider,
                MagicMock(),
                stats_service,
                MagicMock(),
                [{"prefix": "inbox"}],
                project_manager,
                coordinator,
            )
            operation_id = "7706d30d-0504-4e23-9011-a69368d4b6c3"
            result = await application_service.submit_operation_async(
                operation_id,
                "open-project",
                OperationTarget("project", "Async project"),
                {"description": "Async operation"},
            )
            self.assertEqual(result.value.name, "Async project")
            receipt = application_service.get_receipt(operation_id)
            self.assertEqual(receipt.status, "succeeded")
            self.assertEqual(receipt.operation_id, operation_id)
            task_provider.dispose()
            coordinator.close(wait=True)


    async def test_unknown_statistics_write_retains_receipt_and_next_operation_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            coordinator = MutationCoordinator()
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"), coordinator)
            json_provider = TaskJsonProvider(broker, mutation_coordinator=coordinator)
            task_provider = TaskProvider(
                json_provider,
                broker,
                disableThreading=True,
                mutation_coordinator=coordinator,
            )
            today = TimePoint.today().as_int()
            broker.writeFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, {
                "tasks": [{
                    "id": "task-partial-1",
                    "description": "Work task",
                    "context": "inbox",
                    "start": today,
                    "due": today,
                    "severity": 1.0,
                    "totalCost": 4.0,
                    "investedEffort": 0.0,
                    "status": " ",
                    "calm": "False",
                    "raised": "ready-event",
                }],
                "projects": [],
            })
            stats_service = StatisticsService(
                broker,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                coordinator,
            )
            project_manager = JsonProjectManager(json_provider, mutation_coordinator=coordinator)
            application_service = TaskApplicationService(
                task_provider,
                MagicMock(),
                stats_service,
                MagicMock(),
                [{"prefix": "inbox"}],
                project_manager,
                coordinator,
            )
            statistics_path = broker.getFilePath(FileRegistry.STATISTICS_JSON)
            original_update = broker._atomicFileStore.update

            def persist_then_report_uncertain(
                path: str,
                updater: Callable[[bytes | None], bytes],
                default: bytes | None = None,
                validator: Callable[[bytes], None] | None = None,
            ) -> bytes:
                saved = original_update(path, updater, default, validator)
                if path == statistics_path:
                    raise AtomicWriteError(
                        path,
                        "directory_fsync",
                        "unknown",
                        True,
                        OSError("directory sync could not be confirmed"),
                    )
                return saved

            broker._atomicFileStore.update = persist_then_report_uncertain
            failing_id = "1db7cb2d-20bc-4b9c-9536-72609b8a9498"
            succeeding_id = "26573ae5-b61e-4b4c-ac6b-76b7030e71bc"
            try:
                with self.assertRaises(OperationFailedError) as failure:
                    await application_service.submit_operation_async(
                        failing_id,
                        "record-work",
                        OperationTarget("task", "task-partial-1"),
                        {"duration": "30m"},
                    )

                self.assertEqual("unknown", failure.exception.effects_state)
                failed_receipt = application_service.get_receipt(failing_id)
                self.assertEqual("failed", failed_receipt.status)
                self.assertEqual("unknown", failed_receipt.failure.effects_state)
                self.assertEqual("1", failed_receipt.failure.details["saved_count"])

                result = await application_service.submit_operation_async(
                    succeeding_id,
                    "edit-task",
                    OperationTarget("task", "task-partial-1"),
                    {"changes": {"description": "Confirmed after uncertain work"}},
                )
                self.assertEqual("Confirmed after uncertain work", result.value.getDescription())
                self.assertEqual("succeeded", application_service.get_receipt(succeeding_id).status)

                document = broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
                persisted_task = next(
                    task for task in document["tasks"] if task["id"] == "task-partial-1"
                )
                self.assertEqual("Confirmed after uncertain work", persisted_task["description"])
                self.assertGreater(float(persisted_task["investedEffort"]), 0)
                statistics = broker.readStatisticsFileContentJson()
                self.assertEqual(1, len(statistics["log"]))
            finally:
                task_provider.dispose()
                coordinator.close(wait=True)


if __name__ == "__main__":
    unittest.main()
