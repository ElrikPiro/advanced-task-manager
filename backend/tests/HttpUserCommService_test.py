import unittest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from src.wrappers.HttpUserCommService import HttpUserCommService
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

    async def test_initialize_and_shutdown(self):
        """Test initialization and shutdown of the service"""
        # Mock the runner, site, and server
        with patch.object(self.service, 'runner') as mock_runner, \
             patch.object(self.service, 'server') as mock_server:
            
            mock_runner.setup = AsyncMock()
            mock_runner.shutdown = AsyncMock()
            mock_site = AsyncMock()
            mock_site.start = AsyncMock()
            mock_site.stop = AsyncMock()
            mock_server.shutdown = AsyncMock()
            
            with patch('src.wrappers.HttpUserCommService.web.TCPSite', return_value=mock_site):
                # Initialize
                await self.service.initialize()
                mock_runner.setup.assert_called_once()
                mock_site.start.assert_called_once()
                self.assertEqual(self.service.req_id_counter, 0)
                
                # Shutdown
                await self.service.shutdown()
                mock_site.stop.assert_called_once()
                mock_runner.shutdown.assert_called_once()
                mock_server.shutdown.assert_called_once()

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
        self.assertEqual(self.service.notificationQueue[0], outbound_message)

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
        
        # Verify we got the correct notifications
        self.assertEqual(len(notifications), 2)
        self.assertEqual(notifications[0], notification1)
        self.assertEqual(notifications[1], notification2)
        
        # Verify the queue is now empty
        self.assertEqual(len(self.service.notificationQueue), 0)

    async def test_getNotifications_empty_queue(self):
        """Test getNotifications returns empty list when queue is empty"""
        notifications = await self.service.getNotifications()
        self.assertEqual(len(notifications), 0)
        self.assertIsInstance(notifications, list)

    async def test_getMessageUpdates_with_pending_messages(self):
        """Test getMessageUpdates returns the first pending message"""
        # Create agents and message
        bot_agent = BotAgent("bot_1", "TestBot", "Test bot")
        user_agent = UserAgent("user_1", "TestUser", "Test user")
        inbound_message = InboundMessage(user_agent, bot_agent, "test_command", ["arg1"])
        
        # Create a future and add to pending messages
        future = asyncio.get_running_loop().create_future()
        self.service.pendingMessages.append((inbound_message, future))
        
        # Get message updates
        updates = await self.service.getMessageUpdates()
        
        # Verify we got the correct message
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0], inbound_message)
        
        # Verify the message was removed from pending
        self.assertEqual(len(self.service.pendingMessages), 0)

    async def test_getMessageUpdates_empty(self):
        """Test getMessageUpdates returns empty list when no pending messages"""
        updates = await self.service.getMessageUpdates()
        self.assertEqual(len(updates), 0)
        self.assertIsInstance(updates, list)

    async def test_sendFile(self):
        """Test sendFile method (currently a no-op)"""
        # This should not raise an error
        await self.service.sendFile(12345, bytearray(b"test data"))


if __name__ == '__main__':
    unittest.main()
