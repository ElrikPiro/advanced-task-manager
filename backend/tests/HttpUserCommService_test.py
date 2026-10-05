import unittest
import asyncio
import logging
import os
import ssl
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from aiohttp.test_utils import make_mocked_request
from src.wrappers.HttpUserCommService import (
    HttpUserCommService,
    _SafeAiohttpAccessLogger,
    _SafeAiohttpServerLogger,
)
from src.wrappers.Messaging import (
    IAgent, OutboundMessage, InboundMessage, MessageContent,
    RenderMode, UserAgent, BotAgent
)


def create_agent_mock():
    """Helper function to create a mock IAgent for testing"""
    mock = Mock(spec=IAgent)
    mock.id = "bot_123"
    mock.name = "TestBot"
    mock.description = "Test bot agent"
    return mock


def build_http_service(agent_mock, notification_history_store=None):
    """Helper function to build HttpUserCommService with mocked web.Server"""
    history_store = notification_history_store or Mock()
    history_store.read.return_value.to_dict.return_value = {
        "schemaVersion": 1,
        "historyId": "history-id",
        "nextSequence": 1,
        "discardedThrough": 0,
        "entries": [],
    }
    with patch('src.wrappers.HttpUserCommService.web.Server'):
        return HttpUserCommService(
            url="localhost",
            port=8080,
            token="test_token_123",
            chat_id=12345,
            agent=agent_mock,
            notification_history_store=history_store,
        )


class TestHttpUserCommService(unittest.TestCase):
    
    def setUp(self):
        self.agent = create_agent_mock()
        self.service = build_http_service(self.agent)

    def test_initialization(self):
        """Test that HttpUserCommService initializes with correct parameters"""
        self.assertEqual(self.service.url, "localhost")
        self.assertEqual(self.service.port, 8080)
        self.assertEqual(self.service.token, "test_token_123")
        self.assertEqual(self.service.chat_id, 12345)
        self.assertEqual(self.service.agent, self.agent)
        self.assertEqual(len(self.service.pendingMessages), 0)

    def test_getBotAgent(self):
        """Test getBotAgent returns the correct agent"""
        bot_agent = self.service.getBotAgent()
        self.assertEqual(bot_agent, self.agent)


class TestHttpUserCommServiceAsync(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.agent = create_agent_mock()
        self.service = build_http_service(self.agent)

    async def test_sendMessage_with_requestId(self):
        """Test sendMessage with a request ID resolves pending message"""
        # Create a bot agent and user agent
        bot_agent = BotAgent("bot_1", "TestBot", "Test bot")
        user_agent = UserAgent("user_1", "TestUser", "Test user")
        
        # Create an inbound message with a request ID
        inbound_message = InboundMessage(user_agent, bot_agent, "test_command", ["arg1"])
        inbound_message.content.requestId = 1
        
        # Create a future for the pending message
        future = asyncio.get_running_loop().create_future()
        self.service.pendingMessages.append((inbound_message, future))
        
        # Create an outbound message with the same request ID
        content = MessageContent(requestId=1, text="Response text")
        outbound_message = OutboundMessage(bot_agent, user_agent, content, RenderMode.RAW_TEXT)
        
        # Send the message
        await self.service.sendMessage(outbound_message)
        
        # Check that the future was resolved
        self.assertTrue(future.done())
        result = future.result()
        self.assertEqual(result, outbound_message)

    async def test_sendMessage_without_requestId_stores_notification(self):
        """Test sendMessage without request ID persists notification text"""
        # Create a bot agent and user agent
        bot_agent = BotAgent("bot_1", "TestBot", "Test bot")
        user_agent = UserAgent("user_1", "TestUser", "Test user")
        
        # Create an outbound message without a request ID
        content = MessageContent(requestId=None, text="Notification message")
        outbound_message = OutboundMessage(bot_agent, user_agent, content, RenderMode.RAW_TEXT)
        
        # Send the message
        await self.service.sendMessage(outbound_message)

        self.service.notification_history_store.append.assert_called_once_with(
            "Notification message"
        )

    async def test_sendMessage_with_invalid_message_type_raises_error(self):
        """Test sendMessage raises ValueError for non-OutboundMessage types"""
        # Create a bot agent and user agent
        bot_agent = BotAgent("bot_1", "TestBot", "Test bot")
        user_agent = UserAgent("user_1", "TestUser", "Test user")
        
        # Create an inbound message (not outbound)
        inbound_message = InboundMessage(user_agent, bot_agent, "test_command", ["arg1"])
        
        # Attempt to send an inbound message should raise ValueError
        with self.assertRaises(ValueError) as context:
            await self.service.sendMessage(inbound_message)
        
        self.assertIn("Only OutboundMessage is supported", str(context.exception))

    async def test_getNotifications_returns_the_persisted_snapshot_repeatedly(self):
        """Reading notification history must not consume saved entries."""
        snapshot = {
            "schemaVersion": 1,
            "historyId": "history-id",
            "nextSequence": 2,
            "discardedThrough": 0,
            "entries": [{
                "id": "history-id:1",
                "sequence": 1,
                "timestamp": "2026-10-04T12:00:00+02:00",
                "text": "Notification 1",
            }],
        }
        store = self.service.notification_history_store
        store.read.return_value.to_dict.return_value = snapshot

        first = await self.service.getNotifications()
        second = await self.service.getNotifications()

        self.assertEqual(first, snapshot)
        self.assertEqual(second, snapshot)
        self.assertEqual(store.read.call_count, 2)

    async def test_getMessageUpdates_empty(self):
        """Test getMessageUpdates returns empty list when no pending messages"""
        updates = await self.service.getMessageUpdates()
        self.assertEqual(len(updates), 0)
        self.assertIsInstance(updates, list)

    async def test_plain_http_request_is_rejected_before_message_admission(self):
        with patch('src.wrappers.HttpUserCommService.web.Server'):
            api_service = HttpUserCommService(
                url="localhost",
                port=8080,
                token="test_token_123",
                chat_id=12345,
                agent=self.agent,
                application_service=Mock(),
            )
        request = make_mocked_request(
            "GET",
            "/api/v1/tasks",
            headers={"Authorization": "Bearer wrong-token"},
        )

        response = await api_service.__handle_request__(request)

        self.assertEqual(response.status, 403)
        self.assertEqual(api_service.pendingMessages, [])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn('"code":"https-required"', response.text)

    async def test_tls_material_is_required_before_server_creation(self):
        with patch('src.wrappers.HttpUserCommService._SafeAiohttpServer') as server:
            api_service = HttpUserCommService(
                url="localhost",
                port=8080,
                token="test_token_123",
                chat_id=12345,
                agent=self.agent,
                application_service=Mock(),
            )

            with self.assertRaisesRegex(RuntimeError, "TLS certificate chain and private key paths are required"):
                await api_service.initialize()

        server.assert_not_called()

    async def test_tls_context_uses_tls12_defaults_without_key_logging(self):
        api_service = HttpUserCommService(
            url="localhost",
            port=8080,
            token="test_token_123",
            chat_id=12345,
            agent=self.agent,
            tls_cert_chain_path="chain.pem",
            tls_private_key_path="private.pem",
            application_service=Mock(),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            keylog_path = str(Path(temporary_directory) / "tls.keys")
            with patch.dict(os.environ, {"SSLKEYLOGFILE": keylog_path}):
                context = api_service._new_tls_context()

        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.protocol, ssl.PROTOCOL_TLS_SERVER)
        self.assertIsNone(context.keylog_filename)

    async def test_invalid_tls_material_is_redacted_and_fails_before_server_creation(self):
        api_service = HttpUserCommService(
            url="localhost",
            port=8080,
            token="sensitive-token",
            chat_id=12345,
            agent=self.agent,
            application_service=Mock(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            cert_path = Path(temporary_directory) / "sensitive-token-chain.pem"
            key_path = Path(temporary_directory) / "private-key.pem"
            cert_path.write_text("invalid certificate", encoding="utf-8")
            key_path.write_text("invalid key", encoding="utf-8")
            api_service.tls_cert_chain_path = str(cert_path)
            api_service.tls_private_key_path = str(key_path)

            with patch('src.wrappers.HttpUserCommService._SafeAiohttpServer') as server:
                with self.assertRaisesRegex(RuntimeError, "TLS certificate chain and private key could not be loaded") as raised:
                    await api_service.initialize()

            server.assert_not_called()
            self.assertNotIn("sensitive-token", str(raised.exception))
            self.assertNotIn(str(cert_path), str(raised.exception))
            self.assertTrue(raised.exception.__suppress_context__)

    async def test_encrypted_key_without_passphrase_fails_without_prompt(self):
        api_service = HttpUserCommService(
            url="localhost",
            port=8080,
            token="test_token_123",
            chat_id=12345,
            agent=self.agent,
            tls_cert_chain_path="certificate-chain.pem",
            tls_private_key_path="encrypted-key.pem",
            application_service=Mock(),
        )
        context = Mock()

        def reject_encrypted_key(*, certfile, keyfile, password):
            self.assertEqual(certfile, "certificate-chain.pem")
            self.assertEqual(keyfile, "encrypted-key.pem")
            self.assertEqual(password(), "")
            raise ssl.SSLError("private key needs a passphrase")

        context.load_cert_chain.side_effect = reject_encrypted_key
        with patch.object(api_service, "_new_tls_context", return_value=context):
            with patch("src.wrappers.HttpUserCommService._SafeAiohttpServer") as server:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "TLS certificate chain and private key could not be loaded",
                ):
                    await api_service.initialize()

        server.assert_not_called()

    async def test_listener_always_receives_tls_context_and_logs_no_endpoint(self):
        events = []
        history_store = Mock()
        history_store.initialize.side_effect = lambda: events.append("history")
        api_service = HttpUserCommService(
            url="sensitive-host",
            port=8080,
            token="sensitive-token",
            chat_id=12345,
            agent=self.agent,
            tls_cert_chain_path="secret-chain.pem",
            tls_private_key_path="secret-key.pem",
            application_service=Mock(),
            notification_history_store=history_store,
        )
        context = object()
        runner = Mock()
        runner.setup = AsyncMock(side_effect=lambda: events.append("setup"))
        runner.cleanup = AsyncMock()
        site = Mock()
        site.start = AsyncMock(side_effect=lambda: events.append("bind"))

        with patch.object(api_service, "_create_ssl_context", return_value=context):
            with patch("src.wrappers.HttpUserCommService._SafeAiohttpServer") as server:
                server.side_effect = lambda *_args, **_kwargs: events.append("server")
                with patch(
                    "src.wrappers.HttpUserCommService.web.ServerRunner",
                    return_value=runner,
                ):
                    with patch(
                        "src.wrappers.HttpUserCommService.web.TCPSite",
                        return_value=site,
                    ) as tcp_site:
                        with patch("builtins.print") as output:
                            await api_service.initialize()

        tcp_site.assert_called_once_with(
            runner,
            "sensitive-host",
            8080,
            ssl_context=context,
        )
        server.assert_called_once()
        server_kwargs = server.call_args.kwargs
        self.assertIsInstance(server_kwargs["logger"], _SafeAiohttpServerLogger)
        self.assertEqual(
            server_kwargs["access_log_class"],
            _SafeAiohttpAccessLogger,
        )
        self.assertEqual(server_kwargs["access_log_format"], "")
        output.assert_called_once_with("HTTPS User Communication Service started")
        history_store.initialize.assert_called_once_with()
        self.assertLess(events.index("history"), events.index("server"))
        self.assertLess(events.index("history"), events.index("bind"))

    async def test_aiohttp_server_logger_redacts_parser_exception(self):
        logger = _SafeAiohttpServerLogger()

        with self.assertLogs("aiohttp.server", level="ERROR") as captured:
            logger.exception(
                "Request contained sensitive-token",
                exc_info=ValueError("sensitive-token"),
            )

        self.assertEqual(len(captured.records), 1)
        self.assertEqual(
            captured.records[0].getMessage(),
            "HTTP request processing failed",
        )
        self.assertIsNone(captured.records[0].exc_info)

    async def test_aiohttp_access_logger_omits_request_target_and_headers(self):
        access_logger = _SafeAiohttpAccessLogger(
            logging.getLogger("aiohttp.access.http_api"),
            "",
        )

        with self.assertLogs("aiohttp.access", level="INFO") as captured:
            access_logger.log(
                Mock(url="/tasks?sensitive-token"),
                Mock(status=401),
                0.25,
            )

        self.assertEqual(len(captured.records), 1)
        self.assertEqual(
            captured.records[0].getMessage(),
            "HTTP request completed status=401 elapsed=0.250",
        )
        self.assertNotIn("sensitive-token", captured.output[0])

    async def test_sendFile(self):
        """Test sendFile method (currently a no-op)"""
        # This should not raise an error
        await self.service.sendFile(12345, bytearray(b"test data"))


if __name__ == '__main__':
    unittest.main()
