"""Exercise the HTTP resource contract against real task and file providers."""

from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from threading import Event
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from urllib.parse import quote
from uuid import uuid4

from aiohttp.test_utils import TestClient, TestServer

from src.FileBroker import FileBroker
from src.HeuristicScheduling import HeuristicScheduling
from src.JsonProjectManager import JsonProjectManager
from src.MutationCoordinator import MutationCoordinator
from src.ProjectManager import ObsidianProjectManager
from src.Interfaces.IFileBroker import FileRegistry
from src.Utils import TaskDiscoveryPolicies
from src.api.HttpApiV1 import HttpApiV1
from src.domain.TaskApplicationService import TaskApplicationService
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.taskproviders.TaskProvider import ConfirmedTaskRefreshError, TaskPrepareError, TaskProvider
from src.wrappers.TimeManagement import TimeAmount, TimePoint

TOKEN = "integration-token"
PREFIX = "/mount/manager/api/v1"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class HttpApiV1IntegrationTest(IsolatedAsyncioTestCase):
    """Validate HTTP semantics while persistence runs through production providers."""

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        from tests.ApplicationReadIntegration_test import ApplicationReadIntegrationTest

        self.helper = ApplicationReadIntegrationTest()
        self.coordinator = MutationCoordinator()
        self.application, self.task_provider, self.project_manager, self.broker = self._json_stack()
        self.api = HttpApiV1(self.application, TOKEN, PREFIX)

    async def asyncSetUp(self) -> None:
        self.client = TestClient(TestServer(self.api.create_app()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.task_provider.dispose()
        self.coordinator.close()
        self.temporary.cleanup()

    def _json_stack(self) -> tuple[TaskApplicationService, TaskProvider, JsonProjectManager, FileBroker]:
        data = self.root / "json-data"
        appdata = self.root / "appdata"
        vault = self.root / "vault"
        data.mkdir(parents=True)
        appdata.mkdir()
        vault.mkdir()
        now = TimePoint(datetime.datetime(2026, 10, 4, 12, 0))
        start = (now + TimeAmount("-1d")).as_int()
        due = (now + TimeAmount("30d")).as_int()
        tasks = [
            self._task("task /+one", "Original task", start, due, raised="release"),
            self._task("waiting-task", "Waiting task", start, due, waited="release"),
            self._task("waiting-task-2", "Second waiting task", start, due, waited="release"),
            self._task("schedule-task", "Schedule task", start, due),
            self._task("work-task", "Work task", start, due),
            self._task("snooze-task", "Snooze task", start, due),
            self._task("extra-task", "Extra task", start, due),
        ]
        (data / "tasks.json").write_text(
            json.dumps(
                {
                    "tasks": tasks,
                    "projects": [{
                        "name": "Quarter 1 & follow-up",
                        "description": "Original project description",
                        "status": "open",
                    }],
                }
            ),
            encoding="utf-8",
        )
        (data / "statistics.json").write_text("{}", encoding="utf-8")
        broker = FileBroker(str(data), str(appdata), str(vault), self.coordinator)
        json_provider = TaskJsonProvider(broker, self.coordinator)
        provider = TaskProvider(json_provider, broker, disableThreading=True, mutation_coordinator=self.coordinator)
        scheduling = HeuristicScheduling(TimeAmount("2p"), provider)
        application, _, _, _ = self.helper._create_query_stack(broker, provider, scheduling)
        project_manager = JsonProjectManager(json_provider, self.coordinator)
        application._project_manager = project_manager
        return application, provider, project_manager, broker

    @staticmethod
    def _task(
        task_id: str,
        description: str,
        start: int,
        due: int,
        *,
        raised: str | None = None,
        waited: str | None = None,
    ) -> dict[str, object]:
        return {
            "id": task_id,
            "description": description,
            "context": "work",
            "start": start,
            "due": due,
            "severity": 1.0,
            "totalCost": 8.0,
            "investedEffort": 2.0,
            "status": " ",
            "calm": "False",
            "project": "",
            "raised": raised,
            "waited": waited,
        }

    def _headers(self, media_type: str = "application/hal+json") -> dict[str, str]:
        return {**AUTH, "Accept": media_type}

    def _storage_snapshot(self) -> dict[str, tuple[bool, int, bytes | None]]:
        snapshot: dict[str, tuple[bool, int, bytes | None]] = {}
        for path in self.root.rglob("*"):
            stat = path.stat()
            snapshot[str(path.relative_to(self.root))] = (
                path.is_dir(),
                stat.st_mtime_ns,
                None if path.is_dir() else path.read_bytes(),
            )
        return snapshot

    async def _get_json(self, path: str, *, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any], Any]:
        response = await self.client.get(path, headers=headers or self._headers())
        return response.status, await response.json(), response

    async def _post_operation(
        self,
        operation_type: str,
        target: dict[str, str],
        parameters: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> tuple[int, dict[str, Any], Any]:
        response = await self.client.post(
            f"{PREFIX}/operations",
            headers={**AUTH, "Content-Type": "application/json", "Accept": "application/hal+json"},
            json={
                "id": operation_id or str(uuid4()),
                "type": operation_type,
                "target": target,
                "parameters": parameters,
            },
        )
        return response.status, await response.json(), response

    async def test_resource_routes_prefix_and_live_query_contract(self) -> None:
        with self.helper._fixed_clock():
            status, root, response = await self._get_json(PREFIX + "/")
            self.assertEqual(status, 200)
            self.assertEqual(response.content_type, "application/hal+json")
            self.assertEqual(root["version"], "1")
            self.assertEqual(root["_links"]["tasks"]["href"], PREFIX + "/tasks")
            self.assertEqual(root["_links"]["status"]["href"], PREFIX + "/status")
            self.assertEqual(root["_links"]["self"]["href"], PREFIX)
            self.assertEqual(response.headers["Cache-Control"], "no-store")

            status, service_status, status_response = await self._get_json(PREFIX + "/status")
            self.assertEqual(status, 200)
            self.assertTrue(service_status["ready"])
            self.assertIsNone(service_status["snapshotAgeSeconds"])
            self.assertEqual(status_response.headers["Cache-Control"], "no-store")

            status, page, _ = await self._get_json(
                PREFIX + "/tasks?page=999&pageSize=2&algorithm=" + quote("EDF Algorithm", safe="")
            )
            self.assertEqual(status, 200)
            self.assertEqual(page["total"], 5)
            self.assertEqual(page["page"], 999)
            self.assertEqual(page["_embedded"]["tasks"], [])
            self.assertEqual(page["actions"][0]["name"], "create-task")

            status, detail, _ = await self._get_json(PREFIX + "/tasks/task%20%2F%2Bone")
            self.assertEqual(status, 200)
            self.assertEqual(detail["id"], "task /+one")
            self.assertEqual(detail["_links"]["self"]["href"], PREFIX + "/tasks/task%20%2F%2Bone")
            self.assertEqual({item["name"] for item in detail["actions"]}, {
                "edit-task", "complete-task", "schedule-task", "record-work", "snooze-task"
            })
            self.assertTrue(all(action["method"] == "POST" for action in detail["actions"]))
            self.assertTrue(all(action["href"] == PREFIX + "/operations" for action in detail["actions"]))
            self.assertTrue(all(action["contentType"] == "application/json" for action in detail["actions"]))
            _, events, _ = await self._get_json(PREFIX + "/events")
            self.assertEqual(events["actions"][0]["name"], "raise-event")

            _, open_project, _ = await self._get_json(
                PREFIX + "/projects/Quarter%201%20%26%20follow-up"
            )
            self.assertEqual(
                {item["name"] for item in open_project["actions"]},
                {"close-project", "hold-project", "edit-project-content"},
            )
            _, projects, _ = await self._get_json(PREFIX + "/projects")
            self.assertEqual(projects["actions"][0]["name"], "open-project")

            route_paths = [
                "/agenda?day=2026-10-04",
                "/statistics",
                "/events",
                "/status",
                "/strategies",
                "/projects",
                "/projects/Quarter%201%20%26%20follow-up",
            ]
            for path in route_paths:
                route_status, _, route_response = await self._get_json(PREFIX + path)
                self.assertEqual(route_status, 200, path)
                self.assertEqual(route_response.headers["Cache-Control"], "no-store", path)

        response = await self.client.get(
            PREFIX + "/tasks?notAParameter=1", headers=self._headers()
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(response.content_type, "application/problem+json")
        problem = await response.json()
        self.assertEqual(problem["code"], "unknown-query-parameter")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])
        self.assertEqual(problem["effectsState"], "none")

        response = await self.client.get(
            PREFIX + "/tasks?page=1&page=2", headers=self._headers()
        )
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["code"], "duplicate-query-parameter")
        for invalid_query in (
            "/tasks?page=0",
            "/tasks?pageSize=-1",
            "/tasks?heuristic=unknown",
            "/agenda?day=2026-02-30",
        ):
            response = await self.client.get(PREFIX + invalid_query, headers=self._headers())
            self.assertEqual(response.status, 400, invalid_query)

        response = await self.client.get(PREFIX + "/", headers=self._headers("text/plain"))
        self.assertEqual(response.status, 406)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = await self.client.delete(PREFIX + "/tasks", headers=self._headers())
        self.assertEqual(response.status, 405)
        unsupported_methods = [
            ("POST", PREFIX + "/"),
            ("PATCH", PREFIX + "/tasks"),
            ("POST", PREFIX + "/agenda"),
            ("PATCH", PREFIX + "/statistics"),
            ("POST", PREFIX + "/events"),
            ("POST", PREFIX + "/strategies"),
            ("POST", PREFIX + "/projects"),
            ("PATCH", PREFIX + "/projects/Quarter%201%20%26%20follow-up"),
            ("GET", PREFIX + "/operations"),
            ("POST", PREFIX + "/operations/not-a-uuid"),
        ]
        for method, path in unsupported_methods:
            response = await self.client.request(method, path, headers=self._headers())
            self.assertEqual(response.status, 405, (method, path))
            self.assertEqual(response.headers["Cache-Control"], "no-store", (method, path))

    async def test_task_projection_routes_reuse_one_model_snapshot(self) -> None:
        original_get_task_list = self.task_provider.getTaskList
        with patch.object(self.task_provider, "getTaskList", wraps=original_get_task_list) as get_task_list:
            response = await self.client.get(f"{PREFIX}/tasks", headers=AUTH)
            self.assertEqual(response.status, 200)
            self.assertEqual(get_task_list.call_count, 1)
            get_task_list.reset_mock()
            response = await self.client.get(f"{PREFIX}/tasks/task%20%2F%2Bone", headers=AUTH)
            self.assertEqual(response.status, 200)
            self.assertEqual(get_task_list.call_count, 1)

            get_task_list.reset_mock()
            response = await self.client.get(f"{PREFIX}/agenda?day=2026-10-04", headers=AUTH)
            self.assertEqual(response.status, 200)
            self.assertEqual(get_task_list.call_count, 1)

            get_task_list.reset_mock()
            response = await self.client.get(f"{PREFIX}/statistics", headers=AUTH)
            self.assertEqual(response.status, 200)
            self.assertEqual(get_task_list.call_count, 1)

    async def test_invalidated_index_detail_returns_retryable_503(self) -> None:
        def require_refresh(_task_id: str):
            error = RuntimeError("The indexed task needs refresh")
            error.code = "snapshot-refresh-required"
            raise error

        with patch.object(self.task_provider, "getTaskById", side_effect=require_refresh, create=True):
            response = await self.client.get(
                f"{PREFIX}/tasks/task%20%2F%2Bone",
                headers=AUTH,
            )

        self.assertEqual(response.status, 503)
        self.assertEqual(response.headers["Retry-After"], "1")
        self.assertEqual((await response.json())["code"], "snapshot-refresh-required")

    async def test_vault_listener_serves_status_while_first_snapshot_loads(self) -> None:
        appdata = self.root / "vault-appdata"
        vault = self.root / "obsidian-vault"
        appdata.mkdir()
        vault.mkdir()
        broker = FileBroker(str(self.root / "json-data"), str(appdata), str(vault), self.coordinator)
        json_provider = ObsidianVaultTaskJsonProvider(
            broker,
            TaskDiscoveryPolicies("0", "0", "inbox", []),
            mutation_coordinator=self.coordinator,
            auto_start=False,
        )
        provider = ObsidianTaskProvider(
            json_provider,
            broker,
            mutation_coordinator=self.coordinator,
        )
        with patch.object(provider, "getTaskList", return_value=[]):
            application, _, _, _ = self.helper._create_query_stack(broker, provider)
        application._project_manager = ObsidianProjectManager(
            provider,
            broker,
            self.coordinator,
        )
        api = HttpApiV1(application, TOKEN, PREFIX)
        client = TestClient(TestServer(api.create_app()))
        await client.start_server()

        scan_started = Event()
        release_scan = Event()

        def blocked_inventory(_registry: Any) -> list[tuple[str, float]]:
            scan_started.set()
            release_scan.wait(5)
            return []

        try:
            with patch.object(
                broker,
                "getVaultFilesCancellable",
                side_effect=lambda registry, _cancel: blocked_inventory(registry),
            ):
                provider.start()
                self.assertTrue(await asyncio.to_thread(scan_started.wait, 2))

                root_response = await client.get(PREFIX + "/", headers=AUTH)
                self.assertEqual(root_response.status, 200)
                status_response = await client.get(PREFIX + "/status", headers=AUTH)
                self.assertEqual(status_response.status, 200)
                service_status = await status_response.json()
                self.assertFalse(service_status["ready"])
                self.assertTrue(service_status["refreshing"])

                for path in (
                    "/tasks",
                    "/tasks/unavailable-yet",
                    "/agenda?day=2026-10-04",
                    "/statistics",
                    "/events",
                    "/projects",
                    "/projects/Atlas",
                ):
                    response = await client.get(PREFIX + path, headers=AUTH)
                    self.assertEqual(response.status, 503, path)
                    self.assertEqual((await response.json())["code"], "service-not-ready")
                    self.assertEqual(response.headers["Retry-After"], "1")

                operation_id = str(uuid4())
                create_response = await client.post(
                    PREFIX + "/operations",
                    headers={**AUTH, "Content-Type": "application/json"},
                    json={
                        "id": operation_id,
                        "type": "create-task",
                        "target": {"kind": "tasks"},
                        "parameters": {"description": "Wait for the vault"},
                    },
                )
                create_problem = await create_response.json()
                self.assertEqual(create_response.status, 503)
                self.assertEqual(create_problem["code"], "service-not-ready")
                self.assertEqual(create_problem["effectsState"], "none")
                receipt_response = await client.get(
                    PREFIX + "/operations/" + operation_id,
                    headers=AUTH,
                )
                self.assertEqual(receipt_response.status, 404)

                patch_response = await client.patch(
                    PREFIX + "/tasks/unavailable-yet",
                    headers={
                        **AUTH,
                        "Content-Type": "application/merge-patch+json",
                    },
                    json={"description": "Wait for the vault"},
                )
                patch_problem = await patch_response.json()
                self.assertEqual(patch_response.status, 503)
                self.assertEqual(patch_problem["code"], "service-not-ready")
                self.assertEqual(patch_problem["effectsState"], "none")
            release_scan.set()
            deadline = time.monotonic() + 2
            while not provider.isReady() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            self.assertTrue(provider.isReady())
            ready_response = await client.get(PREFIX + "/tasks", headers=AUTH)
            self.assertEqual(ready_response.status, 200)
        finally:
            release_scan.set()
            await client.close()
            provider.dispose()

    async def test_slow_task_read_does_not_block_other_http_requests(self) -> None:
        original_get_task_list = self.task_provider.getTaskList
        read_started = Event()

        def slow_get_task_list(*, include_completed: bool = False):
            read_started.set()
            time.sleep(0.5)
            return original_get_task_list(include_completed=include_completed)

        with patch.object(self.task_provider, "getTaskList", side_effect=slow_get_task_list):
            started_at = time.perf_counter()
            task_response = asyncio.create_task(self.client.get(f"{PREFIX}/tasks", headers=AUTH))
            self.assertTrue(await asyncio.to_thread(read_started.wait, 2))
            root_response = await self.client.get(f"{PREFIX}/", headers=AUTH)
            root_elapsed = time.perf_counter() - started_at
            task_result = await task_response

        self.assertEqual(root_response.status, 200)
        self.assertEqual(task_result.status, 200)
        self.assertLess(root_elapsed, 0.35)

    async def test_notifications_without_history_store_is_not_advertised_or_created(self) -> None:
        notifications_path = Path(
            self.broker.getFilePath(FileRegistry.NOTIFICATIONS_JSON)
        )
        self.assertFalse(notifications_path.exists())

        status, root, _ = await self._get_json(PREFIX + "/")
        self.assertEqual(status, 200)
        self.assertNotIn("notifications", root["_links"])

        response = await self.client.get(PREFIX + "/notifications", headers=self._headers())
        problem = await response.json()
        self.assertEqual(response.status, 503)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(problem["code"], "notification-history-unavailable")
        self.assertEqual(problem["effectsState"], "none")
        self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertFalse(notifications_path.exists())

    async def test_authentication_precedes_reads_and_admission_and_legacy_gets_are_inert(self) -> None:
        data_path = Path(self.broker.getFilePath(FileRegistry.STANDALONE_TASKS_JSON))
        before = data_path.read_bytes()
        before_storage = self._storage_snapshot()
        with patch.object(
            self.task_provider, "getTaskList", wraps=self.task_provider.getTaskList
        ) as reads, patch.object(
            self.coordinator,
            "run_operation_async",
            new=AsyncMock(wraps=self.coordinator.run_operation_async),
        ) as operations:
            response = await self.client.get(PREFIX + "/tasks", headers={"Authorization": "Bearer wrong"})
            self.assertEqual(response.status, 401)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("Bearer", response.headers["WWW-Authenticate"])
            problem = await response.json()
            self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])
            self.assertEqual(problem["effectsState"], "none")

            response = await self.client.post(
                PREFIX + "/operations",
                headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"},
                data="not parsed before authentication",
            )
            self.assertEqual(response.status, 401)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(reads.call_count, 0)
            self.assertEqual(operations.call_count, 0)

        with patch.object(
            self.coordinator,
            "run_operation_async",
            new=AsyncMock(wraps=self.coordinator.run_operation_async),
        ) as operations:
            with patch.object(
                self.coordinator,
                "run_job_async",
                new=AsyncMock(wraps=self.coordinator.run_job_async),
            ) as jobs:
                for old_path in (
                    "/set?args=task%20description%20changed",
                    "/new",
                    "/work",
                    "/schedule",
                    "/snooze",
                    "/done",
                    "/raise",
                    "/project?args=close%20Quarter",
                    "/task_1",
                    "/next",
                    "/previous",
                    "/search",
                ):
                    response = await self.client.get(old_path, headers=self._headers())
                    self.assertEqual(response.status, 404, old_path)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual((await response.json())["code"], "legacy-route-retired")
                response = await self.client.get("/notifications", headers=self._headers())
                self.assertEqual(response.status, 404)
                self.assertEqual((await response.json())["code"], "notifications-unavailable")
                self.assertEqual(operations.call_count, 0)
                self.assertEqual(jobs.call_count, 0)
        self.assertEqual(data_path.read_bytes(), before)
        self.assertEqual(self._storage_snapshot(), before_storage)

    async def test_resource_gets_and_missing_receipt_do_not_change_storage(self) -> None:
        before = self._storage_snapshot()
        paths = (
            PREFIX + "/",
            PREFIX + "/tasks",
            PREFIX + "/tasks/task%20%2F%2Bone",
            PREFIX + "/agenda?day=2026-10-04",
            PREFIX + "/statistics",
            PREFIX + "/events",
            PREFIX + "/strategies",
            PREFIX + "/projects",
            PREFIX + "/projects/Quarter%201%20%26%20follow-up",
            PREFIX + "/operations/" + str(uuid4()),
        )
        expected_status = [200] * (len(paths) - 1) + [404]
        for path, expected in zip(paths, expected_status):
            response = await self.client.get(path, headers=self._headers())
            self.assertEqual(response.status, expected, path)
            self.assertEqual(response.headers["Cache-Control"], "no-store", path)
            await response.read()
        self.assertEqual(self._storage_snapshot(), before)

    async def test_patch_media_null_dates_and_combined_effort_save_once(self) -> None:
        save_task = patch.object(self.task_provider, "saveTask", wraps=self.task_provider.saveTask)
        with save_task as writes:
            response = await self.client.patch(
                PREFIX + "/tasks/task%20%2F%2Bone",
                headers={**AUTH, "Content-Type": "application/merge-patch+json"},
                json={
                    "description": "Updated once",
                    "start": "2026-10-05T09:15:00+02:00",
                    "totalCost": {"value": "3.25", "unit": "pomodoro"},
                    "raised": None,
                },
            )
        self.assertEqual(response.status, 200)
        self.assertEqual(writes.call_count, 1)
        task = await response.json()
        self.assertEqual(task["description"], "Updated once")
        self.assertGreater(float(task["totalCost"]["value"]), 3.2)
        self.assertLess(float(task["totalCost"]["value"]), 3.3)
        self.assertEqual(task["totalCost"]["unit"], "pomodoro")
        parsed_start = datetime.datetime.fromisoformat(task["start"])
        self.assertIsNotNone(parsed_start.tzinfo)
        self.assertEqual(
            parsed_start.timestamp(),
            datetime.datetime(2026, 10, 5, 7, 15, tzinfo=datetime.timezone.utc).timestamp(),
        )
        self.assertIsNone(task["raised"])

        operation_id = str(uuid4())
        with patch.object(self.task_provider, "saveTask", wraps=self.task_provider.saveTask) as writes:
            status, receipt, response = await self._post_operation(
                "edit-task",
                {"kind": "task", "id": "task /+one"},
                {
                    "changes": {"description": "Combined edit"},
                    "effortDelta": {"value": "0.5", "unit": "pomodoro"},
                },
                operation_id=operation_id,
            )
        self.assertEqual(status, 201)
        self.assertEqual(writes.call_count, 1)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(receipt["result"]["value"]["description"], "Combined edit")
        self.assertEqual(receipt["parameters"]["effortDelta"], "0.5p")

        before = self.broker.readFileContentJson(
            FileRegistry.STANDALONE_TASKS_JSON
        )
        for patch_value in (
            {"context": None},
            {"totalCost": {"value": "NaN", "unit": "pomodoro"}},
            {"unknownField": "no"},
        ):
            response = await self.client.patch(
                PREFIX + "/tasks/task%20%2F%2Bone",
                headers={**AUTH, "Content-Type": "application/merge-patch+json"},
                json=patch_value,
            )
            self.assertEqual(response.status, 400)
            self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(
            self.broker.readFileContentJson(
                FileRegistry.STANDALONE_TASKS_JSON
            ),
            before,
        )

        response = await self.client.patch(
            PREFIX + "/tasks/task%20%2F%2Bone",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"description": "wrong media"},
        )
        self.assertEqual(response.status, 415)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_operations_duplicate_conflict_receipt_and_unknown_receipt_do_not_replay(self) -> None:
        operation_id = str(uuid4())
        request = {
            "id": operation_id,
            "type": "create-task",
            "target": {"kind": "tasks"},
            "parameters": {"description": "Created exactly once"},
        }
        path = PREFIX + "/operations"
        headers = {**AUTH, "Content-Type": "application/json"}
        first_response = await self.client.post(path, headers=headers, json=request)
        first = await first_response.json()
        self.assertEqual(first_response.status, 201)
        self.assertEqual(first_response.headers["Location"], f"{PREFIX}/operations/{operation_id}")
        self.assertEqual(first_response.headers["Cache-Control"], "no-store")

        with patch.object(self.task_provider, "saveTask", wraps=self.task_provider.saveTask) as writes:
            duplicate_response = await self.client.post(path, headers=headers, json=request)
            duplicate = await duplicate_response.json()
        self.assertEqual(duplicate_response.status, 201)
        self.assertEqual(writes.call_count, 0)
        self.assertEqual(
            duplicate["result"]["value"]["id"],
            first["result"]["value"]["id"],
        )
        self.assertEqual(
            duplicate["result"]["value"]["description"],
            first["result"]["value"]["description"],
        )

        response = await self.client.get(f"{PREFIX}/operations/{operation_id}", headers=self._headers())
        receipt = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(receipt["id"], operation_id)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

        changed = {**request, "parameters": {"description": "Different intent"}}
        response = await self.client.post(path, headers=headers, json=changed)
        problem = await response.json()
        self.assertEqual(response.status, 409)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(problem["code"], "operation-id-conflict")
        self.assertEqual(problem["operationId"], operation_id)
        self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])

        absent_id = str(uuid4())
        before_absent_receipt = self._storage_snapshot()
        with patch.object(self.task_provider, "saveTask", wraps=self.task_provider.saveTask) as writes:
            response = await self.client.get(f"{PREFIX}/operations/{absent_id}", headers=self._headers())
        self.assertEqual(response.status, 404)
        unavailable = await response.json()
        self.assertEqual(unavailable["code"], "operation-result-unavailable")
        self.assertEqual(unavailable["effectsState"], "unknown")
        self.assertEqual(unavailable["requestId"], response.headers["X-Request-ID"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(writes.call_count, 0)
        self.assertEqual(self._storage_snapshot(), before_absent_receipt)

        invalid = {**request, "id": str(uuid4()), "parameters": {"description": "x", "surprise": True}}
        before_invalid = self._storage_snapshot()
        with patch.object(
            self.coordinator,
            "run_operation_async",
            new=AsyncMock(wraps=self.coordinator.run_operation_async),
        ) as admitted, patch.object(
            self.task_provider, "getTaskList", wraps=self.task_provider.getTaskList
        ) as reads:
            response = await self.client.post(path, headers=headers, json=invalid)
        self.assertEqual(response.status, 400)
        self.assertEqual(admitted.call_count, 0)
        self.assertEqual(reads.call_count, 0)
        self.assertEqual(self._storage_snapshot(), before_invalid)

        response = await self.client.post(path, headers={**AUTH, "Content-Type": "text/plain"}, data="{}")
        self.assertEqual(response.status, 415)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_failed_operations_report_none_partial_and_unknown_effects(self) -> None:
        none_id = str(uuid4())
        before_none = self.broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        with patch.object(self.task_provider, "saveTask", side_effect=TaskPrepareError("rejected before write")):
            status, none_problem, response = await self._post_operation(
                "edit-task",
                {"kind": "task", "id": "task /+one"},
                {"changes": {"description": "Must stay unchanged"}},
                operation_id=none_id,
            )
        self.assertEqual(status, 500)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(none_problem["code"], "operation-failed")
        self.assertEqual(none_problem["effectsState"], "none")
        self.assertEqual(none_problem["operationId"], none_id)
        self.assertEqual(none_problem["requestId"], response.headers["X-Request-ID"])
        self.assertEqual(
            self.broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON),
            before_none,
        )
        receipt_response = await self.client.get(
            f"{PREFIX}/operations/{none_id}", headers=self._headers()
        )
        self.assertEqual(receipt_response.status, 200)
        self.assertEqual(receipt_response.headers["Cache-Control"], "no-store")
        self.assertEqual((await receipt_response.json())["failure"]["effectsState"], "none")

        partial_id = str(uuid4())
        original_save = self.task_provider.saveTask
        calls = 0

        def save_first_then_fail(task: Any) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                original_save(task)
                return
            raise TaskPrepareError("second task rejected before write")

        with patch.object(self.task_provider, "saveTask", side_effect=save_first_then_fail):
            status, partial_problem, response = await self._post_operation(
                "raise-event",
                {"kind": "event", "id": "release"},
                {},
                operation_id=partial_id,
            )
        self.assertEqual(status, 500)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(partial_problem["code"], "operation-failed")
        self.assertEqual(partial_problem["effectsState"], "partial")
        self.assertEqual(partial_problem["operationId"], partial_id)
        self.assertEqual(partial_problem["requestId"], response.headers["X-Request-ID"])
        self.assertEqual(partial_problem["savedCount"], 1)
        self.assertEqual(
            [item["href"] for item in partial_problem["savedResources"]],
            [f"{PREFIX}/tasks/waiting-task"],
        )
        stored = self.broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        stored_tasks = {task["id"]: task for task in stored["tasks"]}
        self.assertNotIn("waited", stored_tasks["waiting-task"])
        self.assertEqual(stored_tasks["waiting-task-2"]["waited"], "release")
        receipt_response = await self.client.get(
            f"{PREFIX}/operations/{partial_id}", headers=self._headers()
        )
        self.assertEqual(receipt_response.status, 200)
        self.assertEqual(receipt_response.headers["Cache-Control"], "no-store")
        self.assertEqual((await receipt_response.json())["failure"]["effectsState"], "partial")

        unknown_id = str(uuid4())
        original_save = self.task_provider.saveTask

        def save_then_lose_confirmation(task: Any) -> None:
            original_save(task)
            raise ConfirmedTaskRefreshError("write committed but refresh confirmation failed")

        with patch.object(self.task_provider, "saveTask", side_effect=save_then_lose_confirmation):
            status, unknown_problem, response = await self._post_operation(
                "edit-task",
                {"kind": "task", "id": "task /+one"},
                {"changes": {"description": "Saved despite lost confirmation"}},
                operation_id=unknown_id,
            )
        self.assertEqual(status, 500)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(unknown_problem["code"], "operation-failed")
        self.assertEqual(unknown_problem["effectsState"], "unknown")
        self.assertEqual(unknown_problem["operationId"], unknown_id)
        self.assertEqual(unknown_problem["requestId"], response.headers["X-Request-ID"])
        unknown_stored = self.broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        saved = next(task for task in unknown_stored["tasks"] if task["id"] == "task /+one")
        self.assertEqual(saved["description"], "Saved despite lost confirmation")
        receipt_response = await self.client.get(
            f"{PREFIX}/operations/{unknown_id}", headers=self._headers()
        )
        self.assertEqual(receipt_response.status, 200)
        self.assertEqual(receipt_response.headers["Cache-Control"], "no-store")
        self.assertEqual((await receipt_response.json())["failure"]["effectsState"], "unknown")

    async def test_closed_coordinator_rejects_operation_without_storage_effects(self) -> None:
        operation_id = str(uuid4())
        before = self._storage_snapshot()
        self.coordinator.close()
        status, problem, response = await self._post_operation(
            "create-task",
            {"kind": "tasks"},
            {"description": "Must not be created"},
            operation_id=operation_id,
        )
        self.assertEqual(status, 503)
        self.assertEqual(problem["code"], "service-unavailable")
        self.assertEqual(problem["effectsState"], "none")
        self.assertEqual(problem["operationId"], operation_id)
        self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self._storage_snapshot(), before)

    async def test_all_task_operations_and_json_project_capabilities_use_real_storage(self) -> None:
        with self.helper._fixed_clock():
            steps = [
                ("create-task", {"kind": "tasks"}, {"description": "Created by operation"}),
                ("edit-task", {"kind": "task", "id": "work-task"}, {"changes": {"description": "Edited via operation"}}),
                ("complete-task", {"kind": "task", "id": "waiting-task"}, {}),
                ("schedule-task", {"kind": "task", "id": "schedule-task"}, {"effortPerDay": "2p"}),
                ("record-work", {"kind": "task", "id": "work-task"}, {"duration": "25m"}),
                ("snooze-task", {"kind": "task", "id": "snooze-task"}, {"duration": "5m"}),
                ("raise-event", {"kind": "event", "id": "release"}, {}),
                ("open-project", {"kind": "project", "id": "New project / &"}, {"description": "New description"}),
                ("edit-project-content", {"kind": "project", "id": "Quarter 1 & follow-up"}, {"description": "Changed JSON description"}),
                ("close-project", {"kind": "project", "id": "Quarter 1 & follow-up"}, {}),
                ("hold-project", {"kind": "project", "id": "Quarter 1 & follow-up"}, {}),
            ]
            for operation_type, target, parameters in steps:
                status, receipt, response = await self._post_operation(operation_type, target, parameters)
                self.assertEqual(status, 201, operation_type)
                self.assertEqual(receipt["type"], operation_type)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

        status, project, _ = await self._get_json(PREFIX + "/projects/Quarter%201%20%26%20follow-up")
        self.assertEqual(status, 200)
        self.assertEqual(project["status"], "on-hold")
        self.assertEqual(project["description"], "Changed JSON description")
        self.assertEqual(project["_links"]["self"]["href"], PREFIX + "/projects/Quarter%201%20%26%20follow-up")
        self.assertEqual({action["name"] for action in project["actions"]}, {
            "open-project", "edit-project-content"
        })
        _, created, _ = await self._get_json(PREFIX + "/projects/New%20project%20%2F%20%26")
        self.assertEqual(created["description"], "New description")

    async def test_markdown_project_content_and_status_operations_reflect_storage_capabilities(self) -> None:
        await self.client.close()
        self.task_provider.dispose()
        self.coordinator.close()

        self.coordinator = MutationCoordinator()
        data = self.root / "markdown-data"
        appdata = self.root / "markdown-appdata"
        vault = self.root / "markdown-vault"
        data.mkdir()
        appdata.mkdir()
        vault.mkdir()
        self.helper._write_markdown_fixture(vault)
        broker = FileBroker(str(data), str(appdata), str(vault), self.coordinator)
        policies = TaskDiscoveryPolicies(
            context_missing_policy="0",
            date_missing_policy="0",
            default_context="inbox",
            categories_prefixes=["alert", "work", "home", "inbox"],
        )
        json_provider = ObsidianVaultTaskJsonProvider(
            broker,
            policies,
            self.coordinator,
            auto_start=False,
        )
        json_provider.refresh()
        provider = ObsidianTaskProvider(
            json_provider,
            broker,
            disableThreading=True,
            mutation_coordinator=self.coordinator,
        )
        scheduling = HeuristicScheduling(TimeAmount("2p"), provider)
        application, _, _, _ = self.helper._create_query_stack(broker, provider, scheduling)
        project_manager = ObsidianProjectManager(provider, broker, self.coordinator)
        application._project_manager = project_manager
        self.application = application
        self.task_provider = provider
        self.project_manager = project_manager
        self.broker = broker
        self.api = HttpApiV1(application, TOKEN, PREFIX)
        self.client = TestClient(TestServer(self.api.create_app()))
        await self.client.start_server()

        status, collection, _ = await self._get_json(PREFIX + "/projects")
        self.assertEqual(status, 200)
        self.assertIn("Atlas", [item["name"] for item in collection["_embedded"]["projects"]])
        status, project, _ = await self._get_json(PREFIX + "/projects/Atlas")
        self.assertEqual(status, 200)
        self.assertIn("content", project)
        self.assertNotIn("description", project)
        capabilities = {item["name"]: item for item in project["actions"]}
        edit_inputs = capabilities["edit-project-content"]["inputs"]
        self.assertIn("action", edit_inputs)
        self.assertIn("line", edit_inputs)
        self.assertNotIn("description", edit_inputs)

        _, _, created = await self._post_operation(
            "open-project",
            {"kind": "project", "id": "New & Notes"},
            {"description": "First paragraph."},
        )
        self.assertEqual(created.status, 201)
        _, created_project, _ = await self._get_json(PREFIX + "/projects/New%20%26%20Notes")
        content_lines = created_project["content"].splitlines()
        description_line = content_lines.index("First paragraph.") + 1
        _, _, edited = await self._post_operation(
            "edit-project-content",
            {"kind": "project", "id": "New & Notes"},
            {"action": "replace", "line": description_line, "content": "Revised paragraph."},
        )
        self.assertEqual(edited.status, 201)
        _, after_edit, _ = await self._get_json(PREFIX + "/projects/New%20%26%20Notes")
        self.assertIn("Revised paragraph.", after_edit["content"])
        for operation_type in ("close-project", "hold-project", "open-project"):
            status, _, _ = await self._post_operation(
                operation_type,
                {"kind": "project", "id": "New & Notes"},
                {},
            )
            self.assertEqual(status, 201, operation_type)

        invalid_response = await self.client.post(
            PREFIX + "/operations",
            headers={**AUTH, "Content-Type": "application/json"},
            json={
                "id": str(uuid4()),
                "type": "edit-project-content",
                "target": {"kind": "project", "id": "New & Notes"},
                "parameters": {"description": "JSON-only field"},
            },
        )
        self.assertEqual(invalid_response.status, 400)


if __name__ == "__main__":
    import unittest

    unittest.main()
