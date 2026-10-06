from typing import NoReturn
import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import MagicMock, AsyncMock, call, patch
from types import SimpleNamespace
from src.TelegramReportingService import TelegramReportingService
from src.algorithms.Interfaces.IAlgorithm import IAlgorithm
from src.Interfaces.ITaskModel import ITaskModel
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.errors import SnapshotRefreshRequiredError, ValidationError
from src.domain.models import TaskView
from src.FileBroker import FileBroker
from src.MutationCoordinator import MutationCoordinator
from src.Utils import TaskDiscoveryPolicies
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.Utils import TaskEntry, TaskInformation


class TestTelegramReportingService(unittest.TestCase):

    def setUp(self):
        self.bot = MagicMock()
        self.taskProvider = MagicMock()
        self.scheduling = MagicMock()
        self.statisticsProvider = MagicMock()
        self.task_list_manager = MagicMock()
        self.categories = [{"prefix": "@test"}]
        self.projectManager = MagicMock()
        self.messageBuilder = MagicMock()
        self.user = MagicMock()
        self.logger = MagicMock()
        
        self.bot.sendMessage = AsyncMock()
        self.bot.shutdown = AsyncMock()

        self.telegramReportingService = TelegramReportingService(
            bot=self.bot,
            taskProvider=self.taskProvider,
            scheduling=self.scheduling,
            statiticsProvider=self.statisticsProvider,
            task_list_manager=self.task_list_manager,
            categories=self.categories,
            projectManager=self.projectManager,
            messageBuilder=self.messageBuilder,
            user=self.user,
            logger=self.logger
        )

    def test_dispose(self) -> None:
        # Act
        self.telegramReportingService.dispose()
        
        # Assert
        self.bot.shutdown.assert_called_once()
        self.taskProvider.dispose.assert_called_once()
        # assert run is set to False
        self.assertFalse(self.telegramReportingService.run)

    def test_onTaskListUpdated(self) -> None:
        self.telegramReportingService.onTaskListUpdated()

        self.assertTrue(self.telegramReportingService._task_list_refresh_pending)
        self.assertFalse(self.telegramReportingService._updateFlag)
        self.taskProvider.getTaskList.assert_not_called()
        self.task_list_manager.update_taskList.assert_not_called()

    def test_pending_task_list_refresh_is_applied_by_reporting_thread(self) -> None:
        tasks = [MagicMock(), MagicMock()]
        self.taskProvider.getTaskList.return_value = tasks
        self.telegramReportingService.onTaskListUpdated()

        self.telegramReportingService._drain_pending_task_list_refresh()

        self.assertFalse(self.telegramReportingService._task_list_refresh_pending)
        self.assertTrue(self.telegramReportingService._updateFlag)
        self.task_list_manager.update_taskList.assert_called_once_with(tasks)

    def test_onTaskListUpdated_does_not_read_during_initial_loading(self) -> None:
        application = SimpleNamespace(is_ready=lambda: False)
        self.telegramReportingService._application_service = application

        self.telegramReportingService.onTaskListUpdated()

        self.taskProvider.getTaskList.assert_not_called()
        self.task_list_manager.update_taskList.assert_not_called()

    def test_processMessage_reports_loading_until_task_data_is_ready(self) -> None:
        self.telegramReportingService._application_service = SimpleNamespace(
            is_ready=lambda: False
        )
        task_list_command = AsyncMock()
        self.telegramReportingService.commands = [("/list", task_list_command)]
        message = SimpleNamespace(
            content=SimpleNamespace(text="list", textList=[], requestId=17)
        )

        asyncio.run(self.telegramReportingService.processMessage(message, True))

        task_list_command.assert_not_awaited()
        self.task_list_manager.get_task_list_content.assert_not_called()
        source_content = self.messageBuilder.createOutboundMessage.call_args.kwargs["content"]
        outbound_content = self.messageBuilder.createOutboundMessage.return_value.content
        self.assertEqual(source_content.text, "Task data is still loading. Try again shortly.")
        self.assertEqual(outbound_content.requestId, 17)

    def test_help_remains_available_while_task_data_is_loading(self) -> None:
        self.telegramReportingService._application_service = SimpleNamespace(
            is_ready=lambda: False
        )
        help_command = AsyncMock()
        self.telegramReportingService.helpCommand = help_command
        self.telegramReportingService.commands = []
        message = SimpleNamespace(
            content=SimpleNamespace(text="help", textList=[], requestId=18)
        )

        asyncio.run(self.telegramReportingService.processMessage(message, True))

        help_command.assert_awaited_once_with("/help", True, 18)

    def test_project_mutation_waits_until_task_data_is_loaded(self) -> None:
        self.telegramReportingService._application_service = SimpleNamespace(
            is_ready=lambda: False
        )
        self.telegramReportingService.commands = [
            ("/project", self.telegramReportingService.projectCommand)
        ]
        message = SimpleNamespace(
            content=SimpleNamespace(text="project", textList=["open"], requestId=19)
        )

        asyncio.run(self.telegramReportingService.processMessage(message, True))

        self.projectManager.process_command.assert_not_called()
        source_content = self.messageBuilder.createOutboundMessage.call_args.kwargs["content"]
        self.assertEqual(source_content.text, "Task data is still loading. Try again shortly.")

    def test_listenForEvents_normal(self) -> None:
        # Arrange
        def stop_after_first_call() -> None:
            self.telegramReportingService.run = False

        mockTaskList = [MagicMock(), MagicMock()]
        discoveredTaskList = [MagicMock()]
        self.taskProvider.discoverTasks.return_value = discoveredTaskList
        self.taskProvider.getTaskList.return_value = mockTaskList
        self.telegramReportingService._listenForEvents = AsyncMock(side_effect=stop_after_first_call)

        # Act
        self.telegramReportingService.listenForEvents()

        # Assert
        self.taskProvider.discoverTasks.assert_called_once_with()
        self.taskProvider.registerTaskListUpdatedCallback.assert_called_once_with(self.telegramReportingService.onTaskListUpdated)
        self.assertEqual(
            self.task_list_manager.update_taskList.call_args_list,
            [call(discoveredTaskList), call(mockTaskList)],
        )
        self.telegramReportingService._listenForEvents.assert_awaited_once()

    def test_listenForEvents_exception(self) -> None:
        # Arrange
        def stop_after_first_call() -> NoReturn:
            self.telegramReportingService.MAX_ERRORS = 0  # To speed up the test
            self.telegramReportingService.ERROR_TIMEOUT = 0  # To speed up the test
            raise Exception("Test Exception")

        mockTaskList = [MagicMock(), MagicMock()]
        discoveredTaskList = [MagicMock()]
        self.taskProvider.discoverTasks.return_value = discoveredTaskList
        self.taskProvider.getTaskList.return_value = mockTaskList
        self.telegramReportingService._listenForEvents = AsyncMock(side_effect=stop_after_first_call)

        # Act
        self.telegramReportingService.listenForEvents()

        # Assert
        self.taskProvider.discoverTasks.assert_called_once_with()
        self.taskProvider.registerTaskListUpdatedCallback.assert_called_once_with(self.telegramReportingService.onTaskListUpdated)
        self.assertEqual(
            self.task_list_manager.update_taskList.call_args_list,
            [call(discoveredTaskList), call(mockTaskList)],
        )
        self.telegramReportingService._listenForEvents.assert_awaited_once()

    def test_listenForEvents_logs_safe_diagnostic_for_http_failure(self) -> None:
        self.bot.api = object()
        self.telegramReportingService.MAX_ERRORS = 0
        self.telegramReportingService.ERROR_TIMEOUT = 0
        self.telegramReportingService._listenForEvents = AsyncMock(
            side_effect=RuntimeError("/private/path and secret token")
        )

        self.telegramReportingService.listenForEvents()

        self.assertEqual(
            self.telegramReportingService._lastError,
            "HTTP service failed; diagnostic details are suppressed.",
        )
        logged_error = str(self.logger.error.call_args.args[0])
        self.assertIn("exception_chain=RuntimeError", logged_error)
        self.assertIn("TelegramReportingService.py:", logged_error)
        self.assertNotIn("/private/path", logged_error)
        self.assertNotIn("secret token", logged_error)

    def test_internalListenForEvents_normal(self) -> None:
        # Arrange
        def _stop_after_first_call() -> None:
            self.telegramReportingService.run = False

        MockLastError = MagicMock()
        self.telegramReportingService._lastError = MockLastError
        self.telegramReportingService.runEventLoop = AsyncMock(side_effect=_stop_after_first_call)

        self.bot.initialize = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService._listenForEvents())

        # Assert
        self.bot.initialize.assert_awaited_once()

    def test_background_refresh_starts_after_listener_initialization(self) -> None:
        events: list[str] = []

        class RefreshingProvider:
            def start(self) -> None:
                events.append("refresh")

        self.telegramReportingService.taskProvider = RefreshingProvider()  # type: ignore[assignment]
        self.bot.initialize = AsyncMock(side_effect=lambda: events.append("listener"))

        async def stop_after_start() -> None:
            events.append("loop")
            self.telegramReportingService.run = False

        self.telegramReportingService.runEventLoop = AsyncMock(side_effect=stop_after_start)

        asyncio.run(self.telegramReportingService._listenForEvents())

        self.assertEqual(events, ["listener", "refresh", "loop"])

    def test_async_provider_discovery_retries_after_refresh_completion(self) -> None:
        events: list[str] = []
        discovered = Event()
        service = self.telegramReportingService

        class AsyncApplication(TaskApplicationService):
            def __init__(self) -> None:
                self.ready = False
                self.discovery_attempts = 0

            def uses_background_refresh(self) -> bool:
                return True

            def is_ready(self) -> bool:
                return self.ready

            def start_background_refresh(self) -> None:
                events.append("refresh")
                self.ready = True
                service.onTaskListUpdated()
                service.onTaskRefreshCompleted()

            def discover_initialize(self) -> list[ITaskModel]:
                self.discovery_attempts += 1
                if self.discovery_attempts == 1:
                    raise SnapshotRefreshRequiredError()
                events.append("discover")
                discovered.set()
                return []

        application = AsyncApplication()
        service._application_service = application
        self.bot.initialize = AsyncMock(side_effect=lambda: events.append("listener"))

        async def stop_after_discovery() -> None:
            for _ in range(200):
                if application.discovery_attempts:
                    break
                await asyncio.sleep(0.01)
            service.onTaskRefreshCompleted()
            for _ in range(200):
                if discovered.is_set():
                    break
                await asyncio.sleep(0.01)
            service.run = False

        service.runEventLoop = AsyncMock(side_effect=stop_after_discovery)

        asyncio.run(service._listenForEvents())

        self.assertTrue(discovered.is_set())
        self.assertEqual(events, ["listener", "refresh", "discover"])
        self.assertEqual(application.discovery_attempts, 2)
        self.assertEqual(self.task_list_manager.update_taskList.call_count, 0)

    def test_mutation_callback_does_not_deadlock_reporting_loop(self) -> None:
        coordinator = MutationCoordinator()
        service = self.telegramReportingService
        service.mutation_coordinator = coordinator
        service.chatId = 123
        self.task_list_manager.selected_task.getTaskUID.return_value = "task-1"
        self.task_list_manager.selected_task.getDescription.return_value = "Task"
        self.taskProvider.getTaskList.return_value = []

        class MutatingApplication:
            def is_ready(self) -> bool:
                return True

            async def execute_operation_async(self, *_args, **_kwargs):
                def commit_and_publish_callback():
                    service.onTaskListUpdated()
                    return SimpleNamespace(value=service._taskListManager.selected_task)

                return await coordinator.run_job_async(commit_and_publish_callback)

        service._application_service = MutatingApplication()  # type: ignore[assignment]
        first_message = SimpleNamespace(
            source=SimpleNamespace(id="123"),
            content=SimpleNamespace(text="done", textList=[], requestId=1),
        )
        other_chat_message = SimpleNamespace(
            source=SimpleNamespace(id="456"),
            content=SimpleNamespace(text="ignored", textList=[], requestId=2),
        )
        self.bot.getMessageUpdates = AsyncMock(
            return_value=[first_message, other_chat_message]
        )
        service.checkFilteredListChanges = AsyncMock()

        try:
            asyncio.run(asyncio.wait_for(service.runEventLoop(), timeout=1.0))
        finally:
            coordinator.close(wait=True)

        self.task_list_manager.update_taskList.assert_called_once_with([])
        self.assertFalse(service._task_list_refresh_pending)

    def test_async_maintenance_repeats_for_external_projects_and_coalesces_refreshes(self) -> None:
        entered_second_discovery = Event()
        release_second_discovery = Event()
        projects = ["Existing"]

        class AsyncApplication(TaskApplicationService):
            def __init__(self) -> None:
                self.discovery_projects: list[list[str]] = []
                self.active_discoveries = 0
                self.max_active_discoveries = 0

            def uses_background_refresh(self) -> bool:
                return True

            def is_ready(self) -> bool:
                return True

            def discover_initialize(self) -> list[ITaskModel]:
                self.active_discoveries += 1
                self.max_active_discoveries = max(
                    self.max_active_discoveries, self.active_discoveries
                )
                try:
                    self.discovery_projects.append(list(projects))
                    if len(self.discovery_projects) == 2:
                        entered_second_discovery.set()
                        release_second_discovery.wait(timeout=2)
                    return []
                finally:
                    self.active_discoveries -= 1

        class RefreshProvider:
            callback = None

            def registerRefreshCompletedCallback(self, callback) -> None:
                self.callback = callback

            def publish_generation(self) -> None:
                if self.callback is not None:
                    self.callback()

            def dispose(self) -> None:
                pass

        application = AsyncApplication()
        provider = RefreshProvider()
        service = self.telegramReportingService
        service.taskProvider = provider  # type: ignore[assignment]
        service._application_service = application
        service._start_discovery_maintenance_worker()

        def wait_for_discovery_count(expected: int) -> None:
            for _ in range(200):
                if len(application.discovery_projects) >= expected:
                    return
                threading_event_wait = Event()
                threading_event_wait.wait(0.01)
            self.fail(f"expected at least {expected} maintenance passes")

        try:
            provider.publish_generation()
            wait_for_discovery_count(1)
            self.assertEqual(application.discovery_projects[0], ["Existing"])

            projects.append("ExternalProject")
            provider.publish_generation()
            self.assertTrue(entered_second_discovery.wait(timeout=2))
            provider.publish_generation()
            provider.publish_generation()
            release_second_discovery.set()
            wait_for_discovery_count(3)

            self.assertIn("ExternalProject", application.discovery_projects[1])
            self.assertIn("ExternalProject", application.discovery_projects[2])
            self.assertEqual(application.max_active_discoveries, 1)
            Event().wait(0.05)
            self.assertEqual(len(application.discovery_projects), 3)
        finally:
            release_second_discovery.set()
            service._maintenance_stop.set()
            service._maintenance_refresh_ready.set()
            worker = service._maintenance_thread
            if worker is not None:
                worker.join(timeout=2)

    def test_dispose_stops_discovery_preparation_before_any_maintenance_commit(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            appdata = root / "appdata"
            vault = root / "vault"
            data.mkdir()
            appdata.mkdir()
            vault.mkdir()
            for name in ("ProjectA", "ProjectB"):
                (vault / f"{name}.md").write_text(
                    f"---\nproject: open\ntrack: work\n---\n# {name}\n",
                    encoding="utf-8",
                )
            coordinator = MutationCoordinator()
            broker = FileBroker(str(data), str(appdata), str(vault), coordinator)
            json_provider = ObsidianVaultTaskJsonProvider(
                broker,
                TaskDiscoveryPolicies("0", "0", "inbox", ["work"]),
                mutation_coordinator=coordinator,
                auto_start=False,
            )
            task_provider = ObsidianTaskProvider(
                json_provider,
                broker,
                mutation_coordinator=coordinator,
            )
            json_provider.refresh()
            application = TaskApplicationService(
                task_provider,
                scheduling=None,
                statistics_service=None,
                task_list_manager=None,
                categories=[],
                mutation_coordinator=coordinator,
            )
            service = TelegramReportingService(
                bot=self.bot,
                taskProvider=task_provider,
                scheduling=self.scheduling,
                statiticsProvider=self.statisticsProvider,
                task_list_manager=self.task_list_manager,
                categories=[],
                projectManager=self.projectManager,
                messageBuilder=self.messageBuilder,
                user=self.user,
                logger=self.logger,
                application_service=application,
                mutation_coordinator=coordinator,
            )
            preparation_started = Event()
            release_preparation = Event()
            provider_stopped = Event()
            original_read = broker.getVaultFileLines
            original_stop = json_provider.stop

            def block_project_read(registry, relative_path):
                if relative_path == "ProjectA.md":
                    preparation_started.set()
                    release_preparation.wait(timeout=2)
                return original_read(registry, relative_path)

            def stop_provider(timeout: float = 2.0) -> None:
                original_stop(timeout)
                provider_stopped.set()

            try:
                with patch.object(
                    broker,
                    "getVaultFileLines",
                    side_effect=block_project_read,
                ), patch.object(json_provider, "stop", side_effect=stop_provider):
                    service._start_discovery_maintenance_worker()
                    service.onTaskRefreshCompleted()
                    self.assertTrue(preparation_started.wait(timeout=2))
                    shutdown = Thread(target=service.dispose)
                    shutdown.start()
                    self.assertTrue(provider_stopped.wait(timeout=2))
                    release_preparation.set()
                    shutdown.join(timeout=3)
                    self.assertFalse(shutdown.is_alive())

                self.assertNotIn("Define next action", (vault / "ProjectA.md").read_text(encoding="utf-8"))
                self.assertNotIn("Define next action", (vault / "ProjectB.md").read_text(encoding="utf-8"))
            finally:
                release_preparation.set()
                task_provider.dispose()
                coordinator.close()

    def test_internalListenForEvents_exception(self) -> None:
        # Arrange
        def _stop_after_first_call() -> None:
            raise Exception("Test Exception")

        MockLastError = MagicMock()
        self.telegramReportingService._lastError = MockLastError
        self.telegramReportingService.runEventLoop = AsyncMock(side_effect=_stop_after_first_call)

        self.bot.initialize = AsyncMock()
        self.bot.shutdown = AsyncMock(side_effect=Exception("Shutdown Exception"))

        # Act
        try:
            asyncio.run(self.telegramReportingService._listenForEvents())
        except Exception:
            pass

        # Assert
        self.bot.initialize.assert_awaited_once()
        self.bot.shutdown.assert_awaited_once()
        
        self.assertFalse(self.telegramReportingService.run)

    def test_hasFilteredListChanged_no_change(self) -> None:
        # Arrange
        mockTaskList = [MagicMock()]
        self.telegramReportingService._taskListManager.filtered_task_list = mockTaskList
        self.telegramReportingService._TelegramReportingService__lastModelList = mockTaskList
        self.taskProvider.compare.return_value = True

        # Act
        result = self.telegramReportingService.hasFilteredListChanged()

        # Assert
        self.assertFalse(result)
        self.taskProvider.compare.assert_called_once_with(mockTaskList, mockTaskList)

    def test_hasFilteredListChanged_with_change(self) -> None:
        # Arrange
        mockTaskList1 = [MagicMock()]
        mockTaskList2 = [MagicMock(), MagicMock()]
        self.telegramReportingService._taskListManager.filtered_task_list = mockTaskList2
        self.telegramReportingService._TelegramReportingService__lastModelList = mockTaskList1
        self.taskProvider.compare.return_value = False

        # Act
        result = self.telegramReportingService.hasFilteredListChanged()

        # Assert
        self.assertTrue(result)
        self.taskProvider.compare.assert_called_once_with(mockTaskList2, mockTaskList1)
        self.assertEqual(self.telegramReportingService._TelegramReportingService__lastModelList, mockTaskList2)

    def test_hasFilteredListChanged_uses_channel_snapshot_with_application_service(self) -> None:
        application_service = MagicMock()
        self.telegramReportingService._application_service = application_service
        channel_tasks = [MagicMock()]
        self.task_list_manager.filtered_task_list = channel_tasks
        self.taskProvider.compare.return_value = False

        changed = self.telegramReportingService.hasFilteredListChanged()

        self.assertTrue(changed)
        self.taskProvider.compare.assert_called_once_with(channel_tasks, [])
        application_service.query_tasks.assert_not_called()
        application_service.read_task.assert_not_called()

    def test_hasFilteredListChanged_preserves_application_view_page(self) -> None:
        application_service = MagicMock()
        self.telegramReportingService._application_service = application_service
        channel_tasks = [MagicMock() for _ in range(5)]
        self.task_list_manager.filtered_task_list = channel_tasks
        self.task_list_manager.current_view.return_value = TaskView(page=2, page_size=2)
        self.taskProvider.compare.return_value = False

        changed = self.telegramReportingService.hasFilteredListChanged()

        visible_page = channel_tasks[2:4]
        self.assertTrue(changed)
        self.taskProvider.compare.assert_called_once_with(visible_page, [])
        self.assertEqual(
            self.telegramReportingService._TelegramReportingService__lastModelList,
            visible_page,
        )
        application_service.query_tasks.assert_not_called()
        application_service.read_task.assert_not_called()

    def test_listCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.listCommand())

        # Assert
        self.task_list_manager.reset_pagination.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_nextCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.nextCommand())

        # Assert
        self.task_list_manager.next_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_previousCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.previousCommand())

        # Assert
        self.task_list_manager.prior_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_selectTaskCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        # Create a mock that will pass the isinstance check for ITaskModel
        mock_task = MagicMock(spec=ITaskModel)
        self.task_list_manager.selected_task = mock_task

        # Act
        asyncio.run(self.telegramReportingService.selectTaskCommand("task_1"))

        # Assert
        self.task_list_manager.select_task.assert_called_once_with("task_1")
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_checkFilteredListChanges_no_change(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 123
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=False)

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_called_once()
        self.bot.sendMessage.assert_not_awaited()

    def test_checkFilteredListChanges_with_change(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 123
        mock_task = MagicMock()
        mock_task.getProject.return_value = "test_project"
        mock_task.getDescription.return_value = "test_description"
        mock_task.getContext.return_value = "test_context"
        
        # Create a proper mock that will pass isinstance check for IAlgorithm
        mock_algorithm = MagicMock(spec=IAlgorithm)
        mock_algorithm.getDescription.return_value = "test_algorithm_description"
        self.task_list_manager.selected_algorithm = mock_algorithm
        
        filtered_list = [mock_task]
        self.task_list_manager.filtered_task_list = filtered_list
        self.telegramReportingService._TelegramReportingService__lastModelList = filtered_list
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.messageBuilder.createOutboundMessage = MagicMock(return_value=MagicMock())

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_called_once()
        self.task_list_manager.reset_pagination.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_checkFilteredListChanges_does_not_rescan_application_service_tasks(self) -> None:
        application_service = MagicMock()
        self.telegramReportingService._application_service = application_service
        self.telegramReportingService.chatId = 123
        channel_task = MagicMock()
        self.task_list_manager.filtered_task_list = [channel_task]
        self.telegramReportingService._TelegramReportingService__lastModelList = [channel_task]
        algorithm = MagicMock(spec=IAlgorithm)
        algorithm.getDescription.return_value = "Current algorithm"
        self.task_list_manager.selected_algorithm = algorithm
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        application_service.query_tasks.assert_not_called()
        application_service.read_task.assert_not_called()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_checkFilteredListChanges_supports_channel_without_algorithm(self) -> None:
        self.telegramReportingService.chatId = 123
        task = MagicMock()
        self.telegramReportingService._TelegramReportingService__lastModelList = [task]
        self.task_list_manager.selected_algorithm = None
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.assertEqual(
            self.messageBuilder.createOutboundMessage.call_args.kwargs["content"].text,
            "No algorithm selected",
        )

    def test_checkFilteredListChanges_chat_id_zero(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 0
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_not_called()
        self.bot.sendMessage.assert_not_awaited()

    def test_runEventLoop_no_messages(self) -> None:
        # Arrange
        self.bot.getMessageUpdates = AsyncMock(return_value=[])
        self.telegramReportingService.checkFilteredListChanges = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.runEventLoop())

        # Assert
        self.statisticsProvider.initialize.assert_called_once()
        self.telegramReportingService.checkFilteredListChanges.assert_awaited_once()
        self.bot.getMessageUpdates.assert_awaited_once()

    def test_runEventLoop_with_messages_valid_chat(self) -> None:
        # Arrange
        mock_message = MagicMock()
        mock_message.source.id = "123"
        messages = [mock_message]
        
        self.bot.getMessageUpdates = AsyncMock(return_value=messages)
        self.telegramReportingService.checkFilteredListChanges = AsyncMock()
        self.telegramReportingService.processMessage = AsyncMock()
        self.telegramReportingService.chatId = 123

        # Act
        asyncio.run(self.telegramReportingService.runEventLoop())

        # Assert
        self.statisticsProvider.initialize.assert_called_once()
        self.telegramReportingService.processMessage.assert_awaited_once_with(mock_message, True)

    def test_runEventLoop_with_messages_new_chat(self) -> None:
        # Arrange
        mock_message = MagicMock()
        mock_message.source.id = 456
        messages = [mock_message]
        
        self.bot.getMessageUpdates = AsyncMock(return_value=messages)
        self.telegramReportingService.checkFilteredListChanges = AsyncMock()
        self.telegramReportingService.processMessage = AsyncMock()
        self.telegramReportingService.chatId = 0

        # Act
        asyncio.run(self.telegramReportingService.runEventLoop())

        # Assert
        self.statisticsProvider.initialize.assert_called_once()
        self.assertEqual(self.telegramReportingService.chatId, 456)
        self.telegramReportingService.processMessage.assert_not_awaited()

    def test_taskInfoCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.taskInfoCommand())

        # Assert
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, True, reqId=None)

    def test_taskInfoCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.taskInfoCommand())

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("No task selected.", reqId=None)

    def test_helpCommand_no_args(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_helpCommand_specific_command(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help list"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_helpCommand_date_help(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help date"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_helpCommand_time_help(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.helpCommand("/help time"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_heuristicListCommand(self) -> None:
        # Arrange
        mock_heuristic_list = {"test": "heuristic"}
        self.task_list_manager.get_heuristic_list.return_value = mock_heuristic_list
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.heuristicListCommand())

        # Assert
        self.task_list_manager.get_heuristic_list.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_algorithmListCommand(self) -> None:
        # Arrange
        mock_algorithm_list = {"test": "algorithm"}
        self.task_list_manager.get_algorithm_list.return_value = mock_algorithm_list
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.algorithmListCommand())

        # Assert
        self.task_list_manager.get_algorithm_list.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_filterListCommand(self) -> None:
        # Arrange
        mock_filter_list = {"filterList": {"test": "filter"}}
        self.task_list_manager.get_filter_list.return_value = mock_filter_list
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.filterListCommand())

        # Assert
        self.task_list_manager.get_filter_list.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_heuristicSelectionCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.heuristicSelectionCommand("test_heuristic"))

        # Assert
        self.task_list_manager.select_heuristic.assert_called_once_with("test_heuristic")
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_algorithmSelectionCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.algorithmSelectionCommand("test_algorithm"))

        # Assert
        self.task_list_manager.select_algorithm.assert_called_once_with("test_algorithm")
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_filterSelectionCommand(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.filterSelectionCommand("test_filter"))

        # Assert
        self.task_list_manager.select_filter.assert_called_once_with("test_filter")
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_doneCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand())

        # Assert
        mock_task.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskList.assert_awaited_once()

    def test_doneCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand())

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task selected.", reqId=None)

    def test_setCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.setCommand("/set description test description"))

        # Assert
        mock_task.setDescription.assert_called_once_with("test description")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_setCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.setCommand("/set description test"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task selected.", reqId=None)

    def test_setCommand_with_two_params(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act - Test with proper parameters
        asyncio.run(self.telegramReportingService.setCommand("/set description test_value"))

        # Assert
        mock_task.setDescription.assert_called_once_with("test_value")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)

    def test_newCommand_with_description(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.taskProvider.createDefaultTask.return_value = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new test task"))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("test task")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.task_list_manager.add_task.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_newCommand_with_extended_params(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.taskProvider.createDefaultTask.return_value = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new test task;@context;2h"))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("test task")
        mock_task.setContext.assert_called_once_with("@context")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.task_list_manager.add_task.assert_called_once_with(mock_task)

    def test_newCommand_no_description(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no description provided.", reqId=None)

    def test_scheduleCommand_with_selected_task_no_split(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.scheduling.schedule.return_value = [mock_task]  # No split, single task returned
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2h"))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_task, "2h")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_scheduleCommand_with_task_splitting(self) -> None:
        # Arrange
        mock_original_task = MagicMock()
        mock_original_task.getDescription.return_value = "Test Task"
        
        mock_split_task1 = MagicMock()
        mock_split_task1.getDescription.return_value = "Test Task 1/2"
        mock_split_task2 = MagicMock()
        mock_split_task2.getDescription.return_value = "Test Task 2/2"
        
        split_tasks = [mock_split_task1, mock_split_task2]
        
        self.task_list_manager.selected_task = mock_original_task
        self.scheduling.schedule.return_value = split_tasks  # Task was split
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 10h"))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_original_task, "10h")
        # Both tasks should be saved
        self.assertEqual(self.taskProvider.saveTask.call_count, 2)
        self.taskProvider.saveTask.assert_any_call(mock_split_task1)
        self.taskProvider.saveTask.assert_any_call(mock_split_task2)
        # New task should be added to task manager (except original)
        # Both new tasks should be added
        self.task_list_manager.add_task.assert_any_call(mock_split_task2)
        # Should send split message
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()
        # Should show first split task
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_split_task1, reqId=None)

    def test_scheduleCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2h"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task provided.", reqId=None)

    def test_workCommand_with_selected_task(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.workCommand("/work 1h"))

        # Assert
        mock_task.setInvestedEffort.assert_called_once()
        mock_task.setTotalCost.assert_called_once()
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.statisticsProvider.doWork.assert_called_once()
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_workCommand_no_selected_task(self) -> None:
        # Arrange
        self.task_list_manager.selected_task = None
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.workCommand("/work 1h"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("no task provided.", reqId=None)

    def test_statsCommand(self) -> None:
        # Arrange
        mock_stats = {"test": "stats"}
        self.task_list_manager.get_list_stats.return_value = mock_stats
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.statsCommand())

        # Assert
        self.task_list_manager.get_list_stats.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_eventsCommand(self) -> None:
        # Arrange
        from src.Utils import EventsContent, EventStatistics
        mock_events_content = EventsContent(
            total_events=3,
            total_raising_tasks=2,
            total_waiting_tasks=1,
            orphaned_events_count=1,
            event_statistics=[
                EventStatistics(
                    event_name="test_event",
                    tasks_raising=2,
                    tasks_waiting=1,
                    is_orphaned=False,
                    orphan_type="none"
                ),
                EventStatistics(
                    event_name="orphaned_event",
                    tasks_raising=1,
                    tasks_waiting=0,
                    is_orphaned=True,
                    orphan_type="raised_only"
                )
            ]
        )
        mock_filtered_tasks = [MagicMock(), MagicMock()]
        self.task_list_manager.filtered_task_list = mock_filtered_tasks
        self.statisticsProvider.getEventStatistics.return_value = mock_events_content
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.eventsCommand())

        self.task_list_manager.getEventStatistics.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_eventsCommand_no_answer(self) -> None:
        # Arrange
        from src.Utils import EventsContent
        mock_events_content = EventsContent(
            total_events=0,
            total_raising_tasks=0,
            total_waiting_tasks=0,
            orphaned_events_count=0,
            event_statistics=[]
        )
        mock_filtered_tasks = []
        self.task_list_manager.filtered_task_list = mock_filtered_tasks
        self.statisticsProvider.getEventStatistics.return_value = mock_events_content
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.eventsCommand("", False))

        self.task_list_manager.getEventStatistics.assert_called_once()
        # When expectAnswer=False, the command still creates and sends the message
        # This is different from other commands - events always sends a response
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_snoozeCommand_default_time(self) -> None:
        # Arrange
        self.telegramReportingService.setCommand = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.snoozeCommand("/snooze"))

        # Assert
        self.telegramReportingService.setCommand.assert_awaited_once_with("/set start now;+5m", reqId=None)

    def test_snoozeCommand_custom_time(self) -> None:
        # Arrange
        self.telegramReportingService.setCommand = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.snoozeCommand("/snooze 10m"))

        # Assert
        self.telegramReportingService.setCommand.assert_awaited_once_with("/set start now;+10m", reqId=None)

    def test_exportCommand_default_format(self) -> None:
        # Arrange
        mock_data = bytearray(b"test data")
        self.taskProvider.exportTasks.return_value = mock_data
        self.bot.sendFile = AsyncMock()
        self.telegramReportingService.chatId = 123

        # Act
        asyncio.run(self.telegramReportingService.exportCommand("/export"))

        # Assert
        self.taskProvider.exportTasks.assert_called_once_with("json")
        self.bot.sendFile.assert_awaited_once_with(chat_id=123, data=mock_data)

    def test_exportCommand_specific_format(self) -> None:
        # Arrange
        mock_data = bytearray(b"test data")
        self.taskProvider.exportTasks.return_value = mock_data
        self.bot.sendFile = AsyncMock()
        self.telegramReportingService.chatId = 123

        # Act
        asyncio.run(self.telegramReportingService.exportCommand("/export json"))

        # Assert
        self.taskProvider.exportTasks.assert_called_once_with("json")
        self.bot.sendFile.assert_awaited_once_with(chat_id=123, data=mock_data)

    def test_importCommand_default_format(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        self.telegramReportingService.listCommand = AsyncMock()
        mock_task_list = [MagicMock()]
        self.taskProvider.getTaskList.return_value = mock_task_list

        # Act
        asyncio.run(self.telegramReportingService.importCommand("/import"))

        # Assert
        self.taskProvider.importTasks.assert_called_once_with("json")
        self.task_list_manager.update_taskList.assert_called_once_with(mock_task_list)
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()
        self.telegramReportingService.listCommand.assert_awaited_once()

    def test_searchCommand_single_result(self) -> None:
        # Arrange
        mock_task = MagicMock()
        mock_manager = MagicMock()
        mock_manager.filtered_task_list = [mock_task]
        self.task_list_manager.search_tasks.return_value = mock_manager
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.searchCommand("/search test"))

        # Assert
        self.task_list_manager.search_tasks.assert_called_once_with(["test"])
        self.assertEqual(self.task_list_manager.selected_task, mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_searchCommand_multiple_results(self) -> None:
        # Arrange
        from src.Utils import TaskListContent
        mock_tasks = [MagicMock(), MagicMock()]
        mock_manager = MagicMock()
        mock_manager.filtered_task_list = mock_tasks
        mock_content = TaskListContent(
            algorithm_name="test_algorithm",
            algorithm_desc="test description",
            sort_heuristic="test_heuristic",
            tasks=[],
            total_tasks=2,
            current_page=1,
            total_pages=1,
            active_filters=[],
            interactive=True
        )
        mock_manager.get_task_list_content.return_value = mock_content
        self.task_list_manager.search_tasks.return_value = mock_manager
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.searchCommand("/search test"))

        # Assert
        self.task_list_manager.search_tasks.assert_called_once_with(["test"])
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_searchCommand_no_results(self) -> None:
        # Arrange
        mock_manager = MagicMock()
        mock_manager.filtered_task_list = []
        self.task_list_manager.search_tasks.return_value = mock_manager
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.searchCommand("/search nonexistent"))

        # Assert
        self.task_list_manager.search_tasks.assert_called_once_with(["nonexistent"])
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("No results found", reqId=None)

    def test_agendaCommand(self) -> None:
        # Arrange
        mock_agenda = {"agenda": "content"}
        self.task_list_manager.get_day_agenda_content.return_value = mock_agenda
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.agendaCommand())

        # Assert
        self.task_list_manager.get_day_agenda_content.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_projectCommand_no_command(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.projectCommand("/project"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("No project command provided", reqId=None)

    def test_projectCommand_invalid_command(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.projectCommand("/project invalid"))

        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("Invalid project command", reqId=None)

    def test_processMessage_calls_handler(self) -> None:
        # Arrange - Test that processMessage method exists and can be called
        from src.wrappers.Messaging import MessageContent
        mock_message = MagicMock()
        mock_message.content = MessageContent(text="test", textList=[])

        # Act - Just verify the method runs without errors
        try:
            asyncio.run(self.telegramReportingService.processMessage(mock_message, True))
            success = True
        except Exception:
            success = False

        # Assert - Method should execute without throwing exceptions
        self.assertTrue(success)

    def test_processMessage_unknown_command(self) -> None:
        # Arrange
        from src.wrappers.Messaging import MessageContent
        mock_message = MagicMock()
        mock_message.content = MessageContent(text="unknown", textList=[])
        self.telegramReportingService.helpCommand = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.processMessage(mock_message, True))

        # Assert
        self.telegramReportingService.helpCommand.assert_awaited_once_with("/unknown", True, None)

    def test_sendTaskList(self) -> None:
        # Arrange
        from src.Utils import TaskListContent
        mock_content = TaskListContent(
            algorithm_name="test_algorithm",
            algorithm_desc="test description",
            sort_heuristic="test_heuristic",
            tasks=[],
            total_tasks=0,
            current_page=1,
            total_pages=1,
            active_filters=[],
            interactive=True
        )
        self.task_list_manager.get_task_list_content.return_value = mock_content
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskList())

        # Assert
        self.task_list_manager.clear_selected_task.assert_called_once()
        self.task_list_manager.get_task_list_content.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_sendTaskInformation(self) -> None:
        # Arrange
        mock_task = MagicMock()
        mock_info = {"task": "info"}
        self.task_list_manager.get_task_information.return_value = mock_info
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskInformation(mock_task))

        # Assert
        self.task_list_manager.get_task_information.assert_called_once_with(mock_task, self.taskProvider, False)
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_sendTaskInformation_extended(self) -> None:
        # Arrange
        mock_task = MagicMock()
        mock_info = {"task": "extended_info"}
        self.task_list_manager.get_task_information.return_value = mock_info
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskInformation(mock_task, True))

        # Assert
        self.task_list_manager.get_task_information.assert_called_once_with(mock_task, self.taskProvider, True)
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_processRelativeTimeSet_now(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "now")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_today(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "today")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_tomorrow(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "tomorrow")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_time_format(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "14:30")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_processRelativeTimeSet_multiple_values(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        current = TimePoint.now()
        
        # Act
        result = self.telegramReportingService.processRelativeTimeSet(current, "today;+2h")
        
        # Assert
        self.assertIsInstance(result, TimePoint)

    def test_setDescriptionCommand(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setDescriptionCommand(mock_task, "New Description"))
        
        # Assert
        mock_task.setDescription.assert_called_once_with("New Description")

    def test_setContextCommand_valid_context(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setContextCommand(mock_task, "@test_context"))
        
        # Assert
        mock_task.setContext.assert_called_once_with("@test_context")

    def test_setContextCommand_invalid_context(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setContextCommand(mock_task, "invalid_context"))
        
        # Assert
        mock_task.setContext.assert_not_called()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_setStartCommand_relative_format(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        mock_task = MagicMock()
        mock_task.getStart.return_value = TimePoint.now()
        
        # Act
        asyncio.run(self.telegramReportingService.setStartCommand(mock_task, "+2h"))
        
        # Assert
        mock_task.setStart.assert_called_once()

    def test_setStartCommand_absolute_format_error_handling(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act & Assert - This tests that the method handles invalid date formats gracefully
        # The actual implementation may throw an error for malformed datetime strings
        with self.assertRaises((ValueError, Exception)):
            asyncio.run(self.telegramReportingService.setStartCommand(mock_task, "invalid-date-format"))

    def test_setDueCommand_relative_format(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimePoint
        mock_task = MagicMock()
        mock_task.getDue.return_value = TimePoint.now()
        
        # Act
        asyncio.run(self.telegramReportingService.setDueCommand(mock_task, "+1d"))
        
        # Assert
        mock_task.setDue.assert_called_once()

    def test_setDueCommand_absolute_format(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setDueCommand(mock_task, "2024-01-01"))
        
        # Assert
        mock_task.setDue.assert_called_once()

    def test_setSeverityCommand(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setSeverityCommand(mock_task, "5.0"))
        
        # Assert
        mock_task.setSeverity.assert_called_once_with(5.0)

    def test_setTotalCostCommand(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setTotalCostCommand(mock_task, "2h"))
        
        # Assert
        mock_task.setTotalCost.assert_called_once()

    def test_setEffortInvestedCommand(self) -> None:
        # Arrange
        from src.wrappers.TimeManagement import TimeAmount
        mock_task = MagicMock()
        mock_task.getInvestedEffort.return_value = TimeAmount("1h")
        mock_task.getTotalCost.return_value = TimeAmount("3h")
        
        # Act
        asyncio.run(self.telegramReportingService.setEffortInvestedCommand(mock_task, "1h"))
        
        # Assert
        mock_task.setInvestedEffort.assert_called_once()
        mock_task.setTotalCost.assert_called_once()

    def test_setCalmCommand_true(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setCalmCommand(mock_task, "true"))
        
        # Assert
        mock_task.setCalm.assert_called_once_with(True)

    def test_setCalmCommand_false(self) -> None:
        # Arrange
        mock_task = MagicMock()
        
        # Act
        asyncio.run(self.telegramReportingService.setCalmCommand(mock_task, "false"))
        
        # Assert
        mock_task.setCalm.assert_called_once_with(False)

    def test_processSetParam_valid_param(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.telegramReportingService.setDescriptionCommand = AsyncMock()
        
        # Act
        asyncio.run(self.telegramReportingService.processSetParam(mock_task, "description", "New Description"))
        
        # Assert
        self.telegramReportingService.setDescriptionCommand.assert_awaited_once_with(mock_task, "New Description", None)

    def test_processSetParam_invalid_param(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        
        # Act
        asyncio.run(self.telegramReportingService.processSetParam(mock_task, "invalid_param", "value"))
        
        # Assert
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()

    def test_nextCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.nextCommand("", False))

        # Assert
        self.task_list_manager.next_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_previousCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.previousCommand("", False))

        # Assert
        self.task_list_manager.prior_page.assert_called_once()
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_selectTaskCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.selectTaskCommand("task_1", False))

        # Assert
        self.task_list_manager.select_task.assert_called_once_with("task_1")
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_heuristicSelectionCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.heuristicSelectionCommand("test", False))

        # Assert
        self.task_list_manager.select_heuristic.assert_called_once_with("test")
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_algorithmSelectionCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.algorithmSelectionCommand("test", False))

        # Assert
        self.task_list_manager.select_algorithm.assert_called_once_with("test")
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_filterSelectionCommand_no_answer(self) -> None:
        # Arrange
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.filterSelectionCommand("test", False))

        # Assert
        self.task_list_manager.select_filter.assert_called_once_with("test")
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_doneCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.sendTaskList = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.doneCommand("", False))

        # Assert
        mock_task.setStatus.assert_called_once_with("x")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskList.assert_not_awaited()

    def test_setCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.setCommand("/set description test", False))

        # Assert
        mock_task.setDescription.assert_called_once_with("test")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_newCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.taskProvider.createDefaultTask.return_value = mock_task
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.newCommand("/new test task", False))

        # Assert
        self.taskProvider.createDefaultTask.assert_called_once_with("test task")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.task_list_manager.add_task.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_scheduleCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.scheduling.schedule.return_value = [mock_task]  # No split
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2h", False))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_task, "2h")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_workCommand_no_answer(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.telegramReportingService.processSetParam = AsyncMock()
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.workCommand("/work 1h", False))

        # Assert
        mock_task.setInvestedEffort.assert_called_once()
        mock_task.setTotalCost.assert_called_once()
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.statisticsProvider.doWork.assert_called_once()
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_sendTaskList_not_interactive(self) -> None:
        # Arrange
        from src.Utils import TaskListContent
        mock_content = TaskListContent(
            algorithm_name="test_algorithm",
            algorithm_desc="test description",
            sort_heuristic="test_heuristic",
            tasks=[],
            total_tasks=0,
            current_page=1,
            total_pages=1,
            active_filters=[],
            interactive=True
        )
        self.task_list_manager.get_task_list_content.return_value = mock_content
        self.messageBuilder.createOutboundMessage.return_value = MagicMock()

        # Act
        asyncio.run(self.telegramReportingService.sendTaskList(False))

        # Assert
        self.task_list_manager.clear_selected_task.assert_called_once()
        self.task_list_manager.get_task_list_content.assert_called_once()
        self.messageBuilder.createOutboundMessage.assert_called_once()
        self.bot.sendMessage.assert_awaited_once()

    def test_checkFilteredListChanges_empty_list(self) -> None:
        # Arrange
        self.telegramReportingService.chatId = 123
        filtered_list = []
        self.task_list_manager.filtered_task_list = filtered_list
        self.telegramReportingService.hasFilteredListChanged = MagicMock(return_value=True)
        self.messageBuilder.createOutboundMessage = MagicMock(return_value=MagicMock())

        # Act
        asyncio.run(self.telegramReportingService.checkFilteredListChanges())

        # Assert
        self.telegramReportingService.hasFilteredListChanged.assert_called_once()
        # When filtered list is empty, the method returns early, so these should NOT be called
        self.task_list_manager.reset_pagination.assert_not_called()
        self.messageBuilder.createOutboundMessage.assert_not_called()
        self.bot.sendMessage.assert_not_awaited()

    def test_projectCommand_valid_command(self) -> None:
        # Arrange
        from src.Interfaces.IProjectManager import ProjectCommands
        ProjectCommands.values = MagicMock(return_value=["help"])
        self.projectManager.process_command = MagicMock(return_value="Command executed")
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.projectCommand("/project help"))

        # Assert
        self.projectManager.process_command.assert_called_once_with("help", [])
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once_with("Command executed", reqId=None)

    def test_importCommand_specific_format(self) -> None:
        # Arrange
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()
        self.telegramReportingService.listCommand = AsyncMock()
        mock_task_list = [MagicMock()]
        self.taskProvider.getTaskList.return_value = mock_task_list

        # Act
        asyncio.run(self.telegramReportingService.importCommand("/import json"))

        # Assert
        self.taskProvider.importTasks.assert_called_once_with("json")
        self.task_list_manager.update_taskList.assert_called_once_with(mock_task_list)
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_awaited_once()
        self.telegramReportingService.listCommand.assert_awaited_once()

    def test_scheduleCommand_no_params(self) -> None:
        # Arrange
        mock_task = MagicMock()
        self.task_list_manager.selected_task = mock_task
        self.scheduling.schedule.return_value = [mock_task]  # No split
        self.telegramReportingService.sendTaskInformation = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule"))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_task, "")
        self.taskProvider.saveTask.assert_called_once_with(mock_task)
        self.telegramReportingService.sendTaskInformation.assert_awaited_once_with(mock_task, reqId=None)

    def test_scheduleCommand_task_splitting_no_answer(self) -> None:
        # Arrange
        mock_original_task = MagicMock()
        mock_original_task.getDescription.return_value = "Test Task"
        
        mock_split_task1 = MagicMock()
        mock_split_task1.getDescription.return_value = "Test Task 1/3"
        mock_split_task2 = MagicMock()
        mock_split_task2.getDescription.return_value = "Test Task 2/3"
        mock_split_task3 = MagicMock()
        mock_split_task3.getDescription.return_value = "Test Task 3/3"
        
        split_tasks = [mock_split_task1, mock_split_task2, mock_split_task3]
        
        self.task_list_manager.selected_task = mock_original_task
        self.scheduling.schedule.return_value = split_tasks  # Task was split into 3
        self.telegramReportingService.sendTaskInformation = AsyncMock()
        self.telegramReportingService._TelegramReportingService__send_raw_text_message = AsyncMock()

        # Act
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 15h", False))

        # Assert
        self.scheduling.schedule.assert_called_once_with(mock_original_task, "15h")
        # All tasks should be saved
        self.assertEqual(self.taskProvider.saveTask.call_count, 3)
        # Check that tasks other than the selected_task get added
        self.task_list_manager.add_task.assert_any_call(mock_split_task2)
        self.task_list_manager.add_task.assert_any_call(mock_split_task3)
        # Should not send any messages when expectAnswer=False
        self.telegramReportingService._TelegramReportingService__send_raw_text_message.assert_not_awaited()
        self.telegramReportingService.sendTaskInformation.assert_not_awaited()

    def test_application_service_handles_task_list_agenda_and_detail_reads(self) -> None:
        application = MagicMock()
        application.query_tasks.return_value = SimpleNamespace(tasks=[])
        application.read_agenda.return_value = MagicMock()
        application.read_task_information.return_value = TaskInformation(
            TaskEntry(
                id="task-7",
                description="Task 7",
                context="work",
                start="2026-10-04",
                due="2026-10-05",
                severity=1.0,
                status=" ",
                total_cost=2.0,
                effort_invested=0.0,
                heuristic_value=0.0,
            ),
            None,
        )
        self.telegramReportingService._application_service = application
        self.task_list_manager.current_view.return_value = TaskView()
        task = MagicMock()
        task.getTaskUID.return_value = "task-7"

        asyncio.run(self.telegramReportingService.sendTaskList(interactive=False, reqId=10))
        asyncio.run(self.telegramReportingService.agendaCommand("/agenda", reqId=11))
        asyncio.run(self.telegramReportingService.sendTaskInformation(task, extended=True, reqId=12))

        application.query_tasks.assert_called_once_with(TaskView())
        application.read_agenda.assert_called_once()
        application.read_task_information.assert_called_once_with("task-7", extended=True)
        self.task_list_manager.get_task_list_content.assert_not_called()
        self.task_list_manager.get_day_agenda_content.assert_not_called()
        self.task_list_manager.get_task_information.assert_not_called()
        last_message_content = self.messageBuilder.createOutboundMessage.call_args.kwargs["content"]
        self.assertEqual(last_message_content.taskInformation.task.id, "task-7")

    def test_application_service_receives_all_supported_telegram_mutations(self) -> None:
        application = MagicMock()
        task = MagicMock()
        task.getTaskUID.return_value = "task-7"
        task.getDescription.return_value = "Updated task"
        application.execute_operation_async = AsyncMock(side_effect=[
            SimpleNamespace(value=task),
            SimpleNamespace(value=task),
            SimpleNamespace(value=task),
            SimpleNamespace(value=[task]),
            SimpleNamespace(value=task),
            SimpleNamespace(value=task),
            SimpleNamespace(value=2),
        ])
        self.telegramReportingService._application_service = application
        self.task_list_manager.selected_task = task
        self.taskProvider.getTaskList.return_value = []

        asyncio.run(self.telegramReportingService.doneCommand("/done", expectAnswer=False))
        asyncio.run(self.telegramReportingService.setCommand("/set description Updated", expectAnswer=False))
        asyncio.run(self.telegramReportingService.newCommand("/new Created", expectAnswer=False))
        asyncio.run(self.telegramReportingService.scheduleCommand("/schedule 2p", expectAnswer=False))
        asyncio.run(self.telegramReportingService.workCommand("/work 30m", expectAnswer=False))
        asyncio.run(self.telegramReportingService.snoozeCommand("/snooze 5m", expectAnswer=False))
        asyncio.run(self.telegramReportingService.raiseAlgorithmCommand("/raise ready", expectAnswer=False))

        calls = application.execute_operation_async.await_args_list
        self.assertEqual([entry.args[0] for entry in calls], [
            "complete-task", "edit-task", "create-task", "schedule-task",
            "record-work", "snooze-task", "raise-event",
        ])
        self.assertEqual(calls[0].args[1].id, "task-7")
        self.assertEqual(calls[1].args[2], {"changes": {"description": "Updated"}})
        self.assertEqual(calls[2].args[2], {"description": "Created"})
        self.assertEqual(calls[3].args[2], {"effort_per_day": "2p"})
        self.assertEqual(calls[4].args[2], {"duration": "30m"})
        self.assertEqual(calls[5].args[2], {"duration": "5m"})
        self.assertEqual(calls[6].args[1].id, "ready")
        self.taskProvider.saveTask.assert_not_called()
        self.task_list_manager.get_task_list_content.assert_not_called()

    def test_application_domain_error_is_reported_without_success_response(self) -> None:
        application = MagicMock()
        application.execute_operation_async = AsyncMock(side_effect=ValidationError("invalid field"))
        self.telegramReportingService._application_service = application
        task = MagicMock()
        task.getTaskUID.return_value = "task-7"
        self.task_list_manager.selected_task = task

        asyncio.run(self.telegramReportingService.doneCommand("/done", expectAnswer=True))

        self.bot.sendMessage.assert_awaited_once()
        self.assertEqual(
            self.messageBuilder.createOutboundMessage.call_args.kwargs["content"].text,
            "invalid field",
        )
        self.taskProvider.saveTask.assert_not_called()
        self.task_list_manager.update_taskList.assert_not_called()

    def test_startup_discovery_happens_before_communication_listener_initializes(self) -> None:
        events: list[str] = []
        application = MagicMock()
        application.discover_initialize.side_effect = lambda: events.append("discover") or []
        self.telegramReportingService._application_service = application
        self.taskProvider.getTaskList.return_value = []

        async def stop_after_initialize() -> None:
            events.append("event-loop")
            self.telegramReportingService.run = False

        self.bot.initialize = AsyncMock(side_effect=lambda: events.append("initialize"))
        self.telegramReportingService.runEventLoop = AsyncMock(side_effect=stop_after_initialize)

        self.telegramReportingService.listenForEvents()

        self.assertEqual(events, ["discover", "initialize", "event-loop"])
        application.discover_initialize.assert_called_once_with()
        self.taskProvider.discoverTasks.assert_not_called()


if __name__ == '__main__':
    unittest.main()
