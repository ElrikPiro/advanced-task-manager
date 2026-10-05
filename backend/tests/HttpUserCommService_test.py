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


def build_http_service(agent_mock):
    """Helper function to build HttpUserCommService with mocked web.Server"""
    with patch('src.wrappers.HttpUserCommService.web.Server'):
        return HttpUserCommService(
            url="localhost",
            port=8080,
            token="test_token_123",
            chat_id=12345,
            agent=agent_mock
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
        self.assertEqual(len(self.service.notificationQueue), 0)

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
        """Test sendMessage without request ID stores message in notification queue"""
        # Create a bot agent and user agent
        bot_agent = BotAgent("bot_1", "TestBot", "Test bot")
        user_agent = UserAgent("user_1", "TestUser", "Test user")
        
        # Create an outbound message without a request ID
        content = MessageContent(requestId=None, text="Notification message")
        outbound_message = OutboundMessage(bot_agent, user_agent, content, RenderMode.RAW_TEXT)
        
        # Verify notification queue is empty
        self.assertEqual(len(self.service.notificationQueue), 0)
        
        # Send the message
        await self.service.sendMessage(outbound_message)
        
        # Check that the message was added to notification queue
        self.assertEqual(len(self.service.notificationQueue), 1)
        # The queue stores tuples of (message, timestamp)
        stored_message, stored_timestamp = self.service.notificationQueue[0]
        self.assertEqual(stored_message, outbound_message)
        self.assertIsNotNone(stored_timestamp)

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

    async def test_getNotifications_returns_and_clears_queue(self):
        """Test getNotifications returns all notifications and clears the queue"""
        # Create bot agent and user agent
        bot_agent = BotAgent("bot_1", "TestBot", "Test bot")
        user_agent = UserAgent("user_1", "TestUser", "Test user")
        
        # Add multiple notifications to the queue
        content1 = MessageContent(requestId=None, text="Notification 1")
        notification1 = OutboundMessage(bot_agent, user_agent, content1, RenderMode.RAW_TEXT)
        
        content2 = MessageContent(requestId=None, text="Notification 2")
        notification2 = OutboundMessage(bot_agent, user_agent, content2, RenderMode.RAW_TEXT)
        
        await self.service.sendMessage(notification1)
        await self.service.sendMessage(notification2)
        
        # Verify notifications are in the queue
        self.assertEqual(len(self.service.notificationQueue), 2)
        
        # Get notifications
        notifications = await self.service.getNotifications()
        
        # Verify we got the correct notifications (returns formatted dictionaries)
        self.assertEqual(len(notifications), 2)
        self.assertEqual(notifications[0]['message'], 'Notification 1')
        self.assertEqual(notifications[1]['message'], 'Notification 2')
        self.assertIn('timestamp', notifications[0])
        self.assertIn('timestamp', notifications[1])
        
        # Verify the queue is now empty
        self.assertEqual(len(self.service.notificationQueue), 0)

    async def test_getNotifications_empty_queue(self):
        """Test getNotifications returns empty list when queue is empty"""
        notifications = await self.service.getNotifications()
        self.assertEqual(len(notifications), 0)
        self.assertIsInstance(notifications, list)

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
        api_service = HttpUserCommService(
            url="sensitive-host",
            port=8080,
            token="sensitive-token",
            chat_id=12345,
            agent=self.agent,
            tls_cert_chain_path="secret-chain.pem",
            tls_private_key_path="secret-key.pem",
            application_service=Mock(),
        )
        context = object()
        runner = Mock()
        runner.setup = AsyncMock()
        runner.cleanup = AsyncMock()
        site = Mock()
        site.start = AsyncMock()

        with patch.object(api_service, "_create_ssl_context", return_value=context):
            with patch("src.wrappers.HttpUserCommService._SafeAiohttpServer") as server:
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
