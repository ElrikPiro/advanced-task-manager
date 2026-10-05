"""Exercise persisted notifications through the real local HTTPS listener."""

from __future__ import annotations

import datetime
import json
import socket
import ssl
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from aiohttp import ClientSession, TCPConnector
from aiohttp.test_utils import TestClient, TestServer

from src.Interfaces.IFileBroker import FileRegistry
from src.MutationCoordinator import MutationCoordinator
from src.NotificationHistoryStore import NotificationHistoryStore
from src.api.HttpApiV1 import HttpApiV1
from src.wrappers.HttpUserCommService import HttpUserCommService
from src.wrappers.Messaging import BotAgent, MessageContent, OutboundMessage, RenderMode, UserAgent
from tests.HttpTlsIntegration_test import _Certificates


TOKEN = "notification-api-test-secret"
PREFIX = "/mounted/task-manager/api/v1"


class NotificationApiIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Use real JSON storage, mutation coordination, and loopback TLS requests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.certificate_directory = TemporaryDirectory()
        cls.certificates = _Certificates(Path(cls.certificate_directory.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.certificate_directory.cleanup()

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.coordinator = MutationCoordinator()

        from tests.HttpApiV1_integration_test import HttpApiV1IntegrationTest

        stack_builder = HttpApiV1IntegrationTest()
        stack_builder.root = self.root
        stack_builder.coordinator = self.coordinator
        from tests.ApplicationReadIntegration_test import ApplicationReadIntegrationTest

        stack_builder.helper = ApplicationReadIntegrationTest()
        self.application, self.task_provider, _, self.broker = stack_builder._json_stack()
        self.history_path = Path(self.broker.getFilePath(FileRegistry.NOTIFICATIONS_JSON))
        self.history_store = NotificationHistoryStore(self.broker, self.coordinator, TOKEN)
        self.port = self._free_port()
        self.service = HttpUserCommService(
            "127.0.0.1",
            self.port,
            TOKEN,
            1,
            UserAgent("http-service-test"),
            str(self.certificates.valid_chain),
            str(self.certificates.valid_key),
            self.application,
            PREFIX,
            notification_history_store=self.history_store,
        )
        self.client_context = ssl.create_default_context(cafile=str(self.certificates.ca_cert))
        self.clients: list[ClientSession] = []

    async def asyncTearDown(self) -> None:
        for client in self.clients:
            await client.close()
        await self.service.shutdown()
        self.task_provider.dispose()
        self.coordinator.close()
        self.temporary.cleanup()

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    async def _start(self) -> None:
        await self.service.initialize()

    def _new_client(self) -> ClientSession:
        client = ClientSession(connector=TCPConnector(ssl=self.client_context))
        self.clients.append(client)
        return client

    def _url(self, suffix: str) -> str:
        return f"https://127.0.0.1:{self.port}{PREFIX}{suffix}"

    @staticmethod
    def _headers(token: str = TOKEN) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/hal+json",
        }

    async def _send_notification(self, text: str) -> None:
        bot = BotAgent("notification-source", "notifications", "test source")
        message = OutboundMessage(
            bot,
            UserAgent("notification-recipient"),
            MessageContent(text=text),
            RenderMode.RAW_TEXT,
        )
        await self.service.sendMessage(message)

    async def test_two_https_clients_read_duplicate_messages_without_consuming_them(self) -> None:
        await self._start()
        text = f"Repeated notice carries {TOKEN}"
        await self._send_notification(text)
        await self._send_notification(text)

        stored_before = self.history_path.read_bytes()
        mtime_before = self.history_path.stat().st_mtime_ns
        self.assertNotIn(TOKEN.encode("utf-8"), stored_before)

        first_client = self._new_client()
        second_client = self._new_client()
        root_response = await first_client.get(self._url("/"), headers=self._headers())
        root = await root_response.json()
        self.assertEqual(root_response.status, 200)
        self.assertEqual(
            root["_links"]["notifications"]["href"],
            f"{PREFIX}/notifications",
        )
        self.assertEqual(root_response.headers["Cache-Control"], "no-store")

        payloads: list[dict[str, object]] = []
        for client in (first_client, second_client, first_client, second_client):
            response = await client.get(self._url("/notifications"), headers=self._headers())
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "application/hal+json")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            UUID(response.headers["X-Request-ID"])
            payload = await response.json()
            UUID(payload["historyId"])
            self.assertTrue(
                not payloads or payload["historyId"] == payloads[0]["historyId"]
            )
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["nextSequence"], 3)
            self.assertEqual(payload["discardedThrough"], 0)
            self.assertEqual(payload["retainedFromSequence"], 1)
            self.assertEqual(payload["retainedThroughSequence"], 2)
            self.assertEqual(payload["total"], 2)
            self.assertEqual(payload["_links"]["self"]["href"], f"{PREFIX}/notifications")
            self.assertEqual(payload["_links"]["root"]["href"], PREFIX)
            observed_at = datetime.datetime.fromisoformat(
                payload["observedAt"].replace("Z", "+00:00")
            )
            self.assertIsNotNone(observed_at.utcoffset())
            entries = payload["_embedded"]["notifications"]
            self.assertEqual([entry["sequence"] for entry in entries], [1, 2])
            self.assertEqual(entries[0]["text"], f"Repeated notice carries [redactado]")
            self.assertEqual(entries[1]["text"], entries[0]["text"])
            self.assertNotIn(TOKEN, json.dumps(payload))
            for entry in entries:
                self.assertEqual(entry["historyId"], payload["historyId"])
                self.assertEqual(entry["id"], f"{payload['historyId']}:{entry['sequence']}")
                timestamp = datetime.datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")
                )
                self.assertIsNotNone(timestamp.utcoffset())
            payloads.append(payload)

        stable_fields = (
            "schemaVersion",
            "historyId",
            "nextSequence",
            "discardedThrough",
            "retainedFromSequence",
            "retainedThroughSequence",
            "total",
            "_links",
            "_embedded",
        )
        for payload in payloads[1:]:
            for field in stable_fields:
                self.assertEqual(payload[field], payloads[0][field], field)
        self.assertEqual(self.history_path.read_bytes(), stored_before)
        self.assertEqual(self.history_path.stat().st_mtime_ns, mtime_before)

    async def test_authentication_queries_and_methods_never_change_history(self) -> None:
        await self._start()
        await self._send_notification("visible and persistent")
        before = self.history_path.read_bytes()
        before_mtime = self.history_path.stat().st_mtime_ns
        client = self._new_client()

        for headers in ({"Accept": "application/hal+json"}, self._headers("wrong-token")):
            response = await client.get(self._url("/notifications"), headers=headers)
            self.assertEqual(response.status, 401)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["WWW-Authenticate"], 'Bearer realm="api"')
            problem = await response.json()
            self.assertEqual(response.content_type, "application/problem+json")
            self.assertEqual(problem["code"], "authentication-required")
            self.assertEqual(problem["effectsState"], "none")
            self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])

        for query in ("ack=true", "mask_as_read=true", "maskAsRead=true", "cursor=2"):
            response = await client.get(
                self._url(f"/notifications?{query}"),
                headers=self._headers(),
            )
            self.assertEqual(response.status, 400, query)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            problem = await response.json()
            self.assertEqual(problem["effectsState"], "none")
            self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])

        for method in ("POST", "PATCH", "DELETE"):
            response = await client.request(
                method,
                self._url("/notifications"),
                headers=self._headers(),
                json={} if method != "DELETE" else None,
            )
            self.assertEqual(response.status, 405, method)
            self.assertEqual(response.headers["Cache-Control"], "no-store")

        self.assertEqual(self.history_path.read_bytes(), before)
        self.assertEqual(self.history_path.stat().st_mtime_ns, before_mtime)

    async def test_missing_store_is_unavailable_and_not_advertised_by_standalone_api(self) -> None:
        api = HttpApiV1(self.application, TOKEN, PREFIX)
        client = TestClient(TestServer(api.create_app()))
        await client.start_server()
        try:
            root_response = await client.get(PREFIX + "/", headers=self._headers())
            root = await root_response.json()
            self.assertNotIn("notifications", root["_links"])

            response = await client.get(PREFIX + "/notifications", headers=self._headers())
            self.assertEqual(response.status, 503)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            problem = await response.json()
            self.assertEqual(problem["code"], "notification-history-unavailable")
            self.assertEqual(problem["effectsState"], "none")
            self.assertEqual(problem["requestId"], response.headers["X-Request-ID"])
        finally:
            await client.close()

    async def test_corrupt_history_blocks_listener_start_and_preserves_bytes(self) -> None:
        invalid_bytes = b'{"schemaVersion":1,"historyId":"damaged"'
        self.history_path.write_bytes(invalid_bytes)
        before_mtime = self.history_path.stat().st_mtime_ns

        with self.assertRaisesRegex(RuntimeError, "Notification history could not be initialized"):
            await self.service.initialize()

        self.assertEqual(self.history_path.read_bytes(), invalid_bytes)
        self.assertEqual(self.history_path.stat().st_mtime_ns, before_mtime)
        self.assertFalse(hasattr(self.service, "server"))
        with self.assertRaises(OSError):
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                pass

    async def test_live_reads_report_corrupt_or_missing_history_without_repairing_it(self) -> None:
        await self._start()
        client = self._new_client()
        invalid_bytes = f'{{"invalid":"{TOKEN}"'.encode("utf-8")
        self.history_path.write_bytes(invalid_bytes)
        invalid_mtime = self.history_path.stat().st_mtime_ns

        corrupt_response = await client.get(
            self._url("/notifications"),
            headers=self._headers(),
        )
        self.assertEqual(corrupt_response.status, 500)
        self.assertEqual(corrupt_response.headers["Cache-Control"], "no-store")
        corrupt_problem = await corrupt_response.json()
        self.assertEqual(corrupt_problem["code"], "notification-history-invalid")
        self.assertEqual(corrupt_problem["effectsState"], "none")
        self.assertEqual(corrupt_problem["requestId"], corrupt_response.headers["X-Request-ID"])
        self.assertNotIn(TOKEN, json.dumps(corrupt_problem))
        self.assertEqual(self.history_path.read_bytes(), invalid_bytes)
        self.assertEqual(self.history_path.stat().st_mtime_ns, invalid_mtime)

        preserved_path = self.history_path.with_name("notifications.invalid-backup")
        self.history_path.rename(preserved_path)
        missing_response = await client.get(
            self._url("/notifications"),
            headers=self._headers(),
        )
        self.assertEqual(missing_response.status, 503)
        self.assertEqual(missing_response.headers["Cache-Control"], "no-store")
        missing_problem = await missing_response.json()
        self.assertEqual(missing_problem["code"], "notification-history-unavailable")
        self.assertEqual(missing_problem["effectsState"], "none")
        self.assertEqual(missing_problem["requestId"], missing_response.headers["X-Request-ID"])
        self.assertNotIn(TOKEN, json.dumps(missing_problem))
        self.assertFalse(self.history_path.exists())
        self.assertEqual(preserved_path.read_bytes(), invalid_bytes)


if __name__ == "__main__":
    unittest.main()
