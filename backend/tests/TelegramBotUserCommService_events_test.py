import unittest
import asyncio
from unittest.mock import Mock, AsyncMock
from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.Interfaces.IFileBroker import IFileBroker
from src.wrappers.Messaging import IAgent, OutboundMessage, MessageContent, RenderMode
from src.Utils import EventsContent, EventStatistics


class TestTelegramBotUserCommServiceEvents(unittest.TestCase):

    def setUp(self):
        self.bot = AsyncMock()
        self.file_broker = Mock(spec=IFileBroker)
        self.agent = Mock(spec=IAgent)
        self.service = TelegramBotUserCommService(self.bot, self.file_broker, self.agent)

    def test_render_events_with_data(self):
        # Arrange
        events_content = EventsContent(
            total_events=3,
            total_raising_tasks=5,
            total_waiting_tasks=4,
            orphaned_events_count=1,
            event_statistics=[
                EventStatistics(
                    event_name="event_A",
                    tasks_raising=2,
                    tasks_waiting=2,
                    is_orphaned=False,
                    orphan_type="none"
                ),
                EventStatistics(
                    event_name="event_B",
                    tasks_raising=2,
                    tasks_waiting=1,
                    is_orphaned=False,
                    orphan_type="none"
                ),
                EventStatistics(
                    event_name="orphan_event",
                    tasks_raising=1,
                    tasks_waiting=0,
                    is_orphaned=True,
                    orphan_type="raised_only"
                )
            ]
        )
        
        destination = Mock()
        destination.id = 12345
        
        message_content = MessageContent(eventsContent=events_content)
        message = OutboundMessage(
            source=self.agent,
            destination=destination,
            content=message_content,
            render_mode=RenderMode.EVENTS
        )

        # Act
        asyncio.run(self.service.sendMessage(message))

        # Assert
        self.bot.send_message.assert_awaited_once()
        call_args = self.bot.send_message.await_args
        chat_id, message_text = call_args[0]
        
        self.assertEqual(chat_id, 12345)
        self.assertIn("*Event Statistics Summary:*", message_text)
        self.assertIn("Total Events: 3", message_text)
        self.assertIn("Tasks Raising Events: 5", message_text)
        self.assertIn("Tasks Waiting for Events: 4", message_text)
        self.assertIn("Orphaned Events: 1", message_text)
        # Event names are escaped for Markdown
        self.assertIn("event\\_A", message_text)
        self.assertIn("event\\_B", message_text)
        self.assertIn("orphan\\_event", message_text)
        self.assertIn("ORPHANED (raised)", message_text)
        self.assertIn("/list - return back to the task list", message_text)

    def test_render_events_empty_data(self):
        # Arrange
        events_content = EventsContent(
            total_events=0,
            total_raising_tasks=0,
            total_waiting_tasks=0,
            orphaned_events_count=0,
            event_statistics=[]
        )
        
        destination = Mock()
        destination.id = 12345
        
        message_content = MessageContent(eventsContent=events_content)
        message = OutboundMessage(
            source=self.agent,
            destination=destination,
            content=message_content,
            render_mode=RenderMode.EVENTS
        )

        # Act
        asyncio.run(self.service.sendMessage(message))

        # Assert
        self.bot.send_message.assert_awaited_once()
        call_args = self.bot.send_message.await_args
        chat_id, message_text = call_args[0]
        
        self.assertEqual(chat_id, 12345)
        self.assertIn("*Event Statistics Summary:*", message_text)
        self.assertIn("Total Events: 0", message_text)
        self.assertIn("Tasks Raising Events: 0", message_text)
        self.assertIn("Tasks Waiting for Events: 0", message_text)
        self.assertIn("Orphaned Events: 0", message_text)
        self.assertIn("No events found in the current task list.", message_text)

    def test_render_events_no_events_content(self):
        # Arrange - Test edge case where eventsContent is not EventsContent type
        destination = Mock()
        destination.id = 12345
        
        message_content = MessageContent(eventsContent=None)
        message = OutboundMessage(
            source=self.agent,
            destination=destination,
            content=message_content,
            render_mode=RenderMode.EVENTS
        )

        # Act
        asyncio.run(self.service.sendMessage(message))

        # Assert
        self.bot.send_message.assert_awaited_once()
        call_args = self.bot.send_message.await_args
        chat_id, message_text = call_args[0]
        
        self.assertEqual(chat_id, 12345)
        self.assertEqual(message_text, "No events data available")

    def test_render_events_waited_only_orphan(self):
        # Arrange
        events_content = EventsContent(
            total_events=1,
            total_raising_tasks=0,
            total_waiting_tasks=2,
            orphaned_events_count=1,
            event_statistics=[
                EventStatistics(
                    event_name="waited_event",
                    tasks_raising=0,
                    tasks_waiting=2,
                    is_orphaned=True,
                    orphan_type="waited_only"
                )
            ]
        )
        
        destination = Mock()
        destination.id = 12345
        
        message_content = MessageContent(eventsContent=events_content)
        message = OutboundMessage(
            source=self.agent,
            destination=destination,
            content=message_content,
            render_mode=RenderMode.EVENTS
        )

        # Act
        asyncio.run(self.service.sendMessage(message))

        # Assert
        self.bot.send_message.assert_awaited_once()
        call_args = self.bot.send_message.await_args
        chat_id, message_text = call_args[0]
        
        self.assertEqual(chat_id, 12345)
        self.assertIn("ORPHANED (waited)", message_text)

    def test_render_events_markdown_fallback(self):
        # Arrange
        events_content = EventsContent(
            total_events=1,
            total_raising_tasks=1,
            total_waiting_tasks=1,
            orphaned_events_count=0,
            event_statistics=[
                EventStatistics(
                    event_name="test_event",
                    tasks_raising=1,
                    tasks_waiting=1,
                    is_orphaned=False,
                    orphan_type="none"
                )
            ]
        )
        
        destination = Mock()
        destination.id = 12345
        
        message_content = MessageContent(eventsContent=events_content)
        message = OutboundMessage(
            source=self.agent,
            destination=destination,
            content=message_content,
            render_mode=RenderMode.EVENTS
        )

        # Simulate Markdown parsing failure
        self.bot.send_message.side_effect = [Exception("Markdown error"), None]

        # Act
        asyncio.run(self.service.sendMessage(message))

        # Assert - Should be called twice (first fails, second succeeds)
        self.assertEqual(self.bot.send_message.await_count, 2)

    def test_render_events_long_message_truncation(self):
        # Arrange - Create a very long message to test truncation
        long_event_stats = []
        for i in range(100):
            long_event_stats.append(EventStatistics(
                event_name=f"very_long_event_name_that_will_create_a_long_message_{i:03d}",
                tasks_raising=i,
                tasks_waiting=i + 1,
                is_orphaned=i % 2 == 0,
                orphan_type="raised_only" if i % 2 == 0 else "none"
            ))
        
        events_content = EventsContent(
            total_events=100,
            total_raising_tasks=100,
            total_waiting_tasks=100,
            orphaned_events_count=50,
            event_statistics=long_event_stats
        )
        
        destination = Mock()
        destination.id = 12345
        
        message_content = MessageContent(eventsContent=events_content)
        message = OutboundMessage(
            source=self.agent,
            destination=destination,
            content=message_content,
            render_mode=RenderMode.EVENTS
        )

        # Act
        asyncio.run(self.service.sendMessage(message))

        # Assert
        self.bot.send_message.assert_awaited_once()
        call_args = self.bot.send_message.await_args
        chat_id, message_text = call_args[0]
        
        self.assertEqual(chat_id, 12345)
        # Check that message was truncated if it exceeds Telegram's limit
        if len(message_text) > 4096:
            self.fail("Message should be truncated to fit Telegram's 4096 character limit")
        
        # If truncated, should end with "..."
        if message_text.endswith("\n..."):
            self.assertTrue(len(message_text) <= 4096)


if __name__ == '__main__':
    unittest.main()