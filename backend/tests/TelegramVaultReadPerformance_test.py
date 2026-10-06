import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry
from src.StatisticsService import StatisticsService
from src.TelegramReportingService import TelegramReportingService
from src.TelegramTaskListManager import TelegramTaskListManager
from src.Utils import TaskDiscoveryPolicies
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.domain.TaskApplicationService import TaskApplicationService
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.wrappers.Messaging import BotAgent, InboundMessage, MessageBuilder, RenderMode, UserAgent
from src.wrappers.TimeManagement import TimeAmount


class _AllTasksFilter:
    def filter(self, tasks):
        return list(tasks)

    def getDescription(self):
        return "All tasks"


class _CountingFakeBot:
    def __init__(self, task_file: Path, task_provider: ObsidianTaskProvider, user: UserAgent):
        self.task_file = task_file
        self.task_provider = task_provider
        self.user = user
        self.agent = BotAgent("fake", "Fake bot", "Local test bot")
        self.reporting = None
        self.messages = []
        self.poll_count = 0
        self.reset_counts = None
        self.read_counts = None
        self.measured_seconds = None

    async def initialize(self):
        return None

    async def shutdown(self):
        return None

    def getBotAgent(self):
        return self.agent

    async def sendMessage(self, message):
        self.messages.append(message)
        if message.content.text == "Event loop initialized" and self.reset_counts is not None:
            self.reset_counts()

    async def getMessageUpdates(self):
        self.poll_count += 1
        if self.poll_count == 1:
            self.read_counts_before_first_poll = self.read_counts()
            with self.task_file.open("r", encoding="utf-8") as source:
                original = source.read()
            updated = original.replace("Task 01", "Fresh task after edit")
            with self.task_file.open("w", encoding="utf-8") as destination:
                destination.write(updated)
            modified = time.time() + 5
            os.utime(self.task_file, (modified, modified))
            # External edits become visible through the next published
            # generation; a warm read itself never rescans the vault.
            self.task_provider.TaskJsonProvider.refresh()
            return [InboundMessage(self.user, self.agent, "list", [])]

        self.reporting.run = False
        return []


class TelegramVaultReadPerformanceTest(unittest.TestCase):
    def test_list_command_uses_published_snapshot_after_external_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            for index in range(1, 25):
                due_day = min(index + 6, 28)
                (vault / f"{index:02}.md").write_text(
                    "---\n---\n"
                    f"- [ ] Task {index:02} [track:: work] [starts:: 2026-10-06] "
                    f"[due:: 2026-10-{due_day:02}] [severity:: 1] [remaining_cost:: 4] "
                    f"[invested:: 1] [id:: task-{index:02}]\n",
                    encoding="utf-8",
                )

            broker = FileBroker(str(root / "state"), str(root / "appdata"), str(vault))
            broker.writeFileContentJson(FileRegistry.STATISTICS_JSON, {
                "2026-10-06": 1.0,
                "log": [{"timestamp": 1791280000000, "work_units": 1.0, "task": "Earlier task"}],
            })
            counts = {"inventories": 0, "line_reads": 0, "read_paths": []}
            original_inventory = broker.getVaultFilesCancellable
            original_lines = broker.getVaultFileLines

            def counted_inventory(registry, should_stop):
                counts["inventories"] += 1
                return original_inventory(registry, should_stop)

            def counted_lines(registry, relative_path):
                counts["line_reads"] += 1
                counts["read_paths"].append(relative_path)
                if "measurement_started" in counts:
                    # Model slow local Markdown I/O without depending on the
                    # host's actual filesystem latency.
                    time.sleep(0.005)
                return original_lines(registry, relative_path)

            broker.getVaultFilesCancellable = counted_inventory
            broker.getVaultFileLines = counted_lines

            json_provider = ObsidianVaultTaskJsonProvider(
                broker,
                TaskDiscoveryPolicies("0", "0", "inbox", ["work"]),
                disableThreading=True,
            )
            task_provider = ObsidianTaskProvider(json_provider, broker, disableThreading=True)
            all_filter = _AllTasksFilter()
            heuristic = RemainingEffortHeuristic(TimeAmount("5p"), 1.0)
            statistics = StatisticsService(broker, all_filter, heuristic, heuristic)
            manager = TelegramTaskListManager(
                task_provider.getTaskList(),
                [("EDF", EdfAlgorithm())],
                [("Remaining effort", heuristic)],
                [("All active", all_filter, True)],
                statistics,
            )
            application = TaskApplicationService(
                task_provider,
                scheduling=None,
                statistics_service=statistics,
                task_list_manager=manager,
                categories=[{"prefix": "work"}],
            )

            # With no open project requiring maintenance, repeated discovery
            # should use the published generation without an inventory scan.
            task_provider.discoverTasks()
            counts["inventories"] = 0
            counts["line_reads"] = 0
            counts["read_paths"] = []
            task_provider.discoverTasks()
            warm_discovery_counts = (
                counts["inventories"], counts["line_reads"], tuple(counts["read_paths"])
            )
            self.assertEqual(warm_discovery_counts, (0, 0, ()))

            user = UserAgent("123")
            bot = _CountingFakeBot(vault / "01.md", task_provider, user)
            service = TelegramReportingService(
                bot=bot,
                taskProvider=task_provider,
                scheduling=MagicMock(),
                statiticsProvider=statistics,
                task_list_manager=manager,
                categories=[{"prefix": "work"}],
                projectManager=MagicMock(),
                messageBuilder=MessageBuilder(),
                user=user,
                logger=MagicMock(),
                application_service=application,
            )
            bot.reporting = service

            def reset_counts():
                counts["inventories"] = 0
                counts["line_reads"] = 0
                counts["read_paths"] = []
                counts["measurement_started"] = time.perf_counter()

            bot.reset_counts = reset_counts
            bot.read_counts = lambda: (
                counts["inventories"],
                counts["line_reads"],
                tuple(counts["read_paths"]),
            )
            service.listenForEvents()
            bot.measured_seconds = time.perf_counter() - counts["measurement_started"]

            self.assertEqual(bot.read_counts_before_first_poll, (0, 0, ()))
            self.assertEqual(bot.poll_count, 2)
            task_list_messages = [
                message for message in bot.messages
                if message.content.renderMode == RenderMode.TASK_LIST
            ]
            self.assertEqual(len(task_list_messages), 1)
            fresh_task = task_list_messages[0].content.taskListContent.tasks[0]
            self.assertIn("Fresh task after edit", fresh_task.description)
            self.assertEqual(counts["inventories"], 1)
            self.assertEqual(counts["read_paths"], ["01.md"])
            self.assertEqual(len(task_list_messages[0].content.taskListContent.tasks), 5)
            if os.environ.get("TELEGRAM_PERF_EVIDENCE") == "1":
                print(
                    "warm_poll_before_message="
                    f"inventories={bot.read_counts_before_first_poll[0]},"
                    f"markdown_reads={bot.read_counts_before_first_poll[1]}; "
                    f"fresh_list_after_edit=inventories={counts['inventories']},"
                    f"markdown_reads={counts['line_reads']},paths={counts['read_paths']},"
                    f"elapsed_seconds={bot.measured_seconds:.3f},simulated_read_latency_ms=5; "
                    f"warm_discovery=inventories={warm_discovery_counts[0]},"
                    f"markdown_reads={warm_discovery_counts[1]}"
                )


if __name__ == "__main__":
    unittest.main()
