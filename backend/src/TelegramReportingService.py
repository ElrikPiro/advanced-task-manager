"""
TelegramReportingService
"""

import asyncio
import threading
import datetime
from dataclasses import replace

from time import sleep as sleepSync
from typing import Callable, List, Coroutine, Any, Tuple

from src.algorithms.Interfaces.IAlgorithm import IAlgorithm

from .wrappers.Messaging import IAgent, IMessage, IMessageBuilder, MessageContent, RenderMode

from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskListManager import ITaskListManager
from .Interfaces.IReportingService import IReportingService
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IScheduling import IScheduling
from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.ILogger import ILogger
from .wrappers.interfaces.IUserCommService import IUserCommService
from .wrappers.TimeManagement import TimeAmount, TimePoint
from .domain.TaskApplicationService import TaskApplicationService
from .domain.errors import DomainError
from .domain.models import AgendaQuery, OperationTarget, TaskView
from .MutationCoordinator import MutationCoordinator


class TelegramReportingService(IReportingService):

    def __init__(self, bot: IUserCommService, taskProvider: ITaskProvider, scheduling: IScheduling, statiticsProvider: IStatisticsService, task_list_manager: ITaskListManager, categories: list[dict[str, str]], projectManager: IProjectManager, messageBuilder: IMessageBuilder, user: IAgent, logger: ILogger, application_service: TaskApplicationService | None = None, mutation_coordinator: MutationCoordinator | None = None):
        # Private Attributes
        self.MAX_ERRORS = 30
        self.ERROR_TIMEOUT = 10

        self.run = True
        self.bot = bot
        self._logger = logger
        self.user: IAgent = user
        self.chatId: int = int(user.id)
        self.taskProvider = taskProvider
        self.scheduling = scheduling
        self.statiticsProvider = statiticsProvider
        self.__projectManager = projectManager
        self.__messageBuilder = messageBuilder
        self._application_service = application_service
        self.mutation_coordinator = mutation_coordinator

        self.__lastModelList: List[ITaskModel] = []
        self._updateFlag = False

        self._taskListManager = task_list_manager

        self._lastError = "Event loop initialized"
        self._lock = threading.Lock()

        self._categories = categories

        self.commands: List[Tuple[str, Callable[[str, bool, int | None], Coroutine[Any, Any, Any]]]] = [
            ("/list", self.listCommand),
            ("/next", self.nextCommand),
            ("/previous", self.previousCommand),
            ("/task_", self.selectTaskCommand),
            ("/info", self.taskInfoCommand),
            ("/heuristic_", self.heuristicSelectionCommand),
            ("/heuristic", self.heuristicListCommand),
            ("/filter_", self.filterSelectionCommand),
            ("/filter", self.filterListCommand),
            ("/done", self.doneCommand),
            ("/set", self.setCommand),
            ("/new", self.newCommand),
            ("/schedule", self.scheduleCommand),
            ("/work", self.workCommand),
            ("/stats", self.statsCommand),
            ("/events", self.eventsCommand),
            ("/snooze", self.snoozeCommand),
            ("/export", self.exportCommand),
            ("/import", self.importCommand),
            ("/search", self.searchCommand),
            ("/agenda", self.agendaCommand),
            ("/project", self.projectCommand),
            ("/algorithm_", self.algorithmSelectionCommand),
            ("/algorithm", self.algorithmListCommand),
            ("/raise", self.raiseAlgorithmCommand)
        ]
        pass

    def dispose(self) -> None:
        self.run = False
        try:
            asyncio.run(self.bot.shutdown())
        finally:
            try:
                self.taskProvider.dispose()
            finally:
                if self.mutation_coordinator is not None:
                    self.mutation_coordinator.close(wait=True)
        pass

    def onTaskListUpdated(self) -> None:
        with self._lock:
            self._updateFlag = True
            self._taskListManager.update_taskList(self.taskProvider.getTaskList())

    def listenForEvents(self) -> None:
        # Discovery and its permitted writes happen before the communication
        # service can start an HTTP listener or receive Telegram messages.
        if self._application_service is not None:
            initial_tasks = self._application_service.discover_initialize()
            self._taskListManager.update_taskList(initial_tasks)
        else:
            discover = getattr(self.taskProvider, "discoverTasks", None)
            if callable(discover):
                self._taskListManager.update_taskList(list(discover()))
        self.taskProvider.registerTaskListUpdatedCallback(self.onTaskListUpdated)
        self._taskListManager.update_taskList(self.taskProvider.getTaskList())
        errCount = 0
        while self.run:
            try:
                asyncio.run(self._listenForEvents())
                errCount = 0
            except Exception as e:
                if getattr(self.bot, "api", None) is not None:
                    self._lastError = "HTTP service failed; diagnostic details are suppressed."
                    self._logger.error(self._lastError)
                else:
                    self._lastError = f"Error: {repr(e)}"
                    self._logger.error(self._lastError)
                sleepSync(self.ERROR_TIMEOUT)
                errCount += 1
                if errCount > self.MAX_ERRORS:
                    self._logger.critical("stopping container")
                    self.run = False
                    break

    async def _listenForEvents(self) -> None:
        await self.bot.initialize()
        await self.__send_raw_text_message(self._lastError)
        while self.run:
            try:
                await self.runEventLoop()
            except Exception:
                try:
                    await self.bot.shutdown()
                except Exception as e:
                    if getattr(self.bot, "api", None) is not None:
                        self._logger.critical(
                            "HTTP service shutdown failed; diagnostic details are suppressed."
                        )
                    else:
                        self._logger.critical(f"Fatal error: {repr(e)} shutting down.")
                    self.run = False
                finally:
                    raise

    def hasFilteredListChanged(self) -> bool:
        if self._application_service is not None:
            content = self._application_service.query_tasks(self._current_view())
            tasks = [self._application_service.read_task(entry.id) for entry in content.tasks]
            if self.taskProvider.compare(tasks, self.__lastModelList):
                return False
            self.__lastModelList = tasks
            return True
        filteredList = self._taskListManager.filtered_task_list
        if self.taskProvider.compare(filteredList, self.__lastModelList):
            return False
        self.__lastModelList = filteredList
        return True

    async def checkFilteredListChanges(self) -> None:
        if self.chatId != 0 and self.hasFilteredListChanged():
            # Send the updated list
            if self._application_service is not None:
                content = self._application_service.query_tasks(self._current_view())
                if not content.tasks:
                    return
                task = self._application_service.read_task(content.tasks[0].id)
                algorithm_description = content.algorithm_desc
            else:
                filteredList = self._taskListManager.filtered_task_list
                if len(filteredList) == 0:
                    return
                task = filteredList[0]
                algorithm = self._taskListManager.selected_algorithm
                assert isinstance(algorithm, IAlgorithm)
                algorithm_description = algorithm.getDescription()
            self._taskListManager.reset_pagination()
            message = self.__messageBuilder.createOutboundMessage(
                source=self.bot.getBotAgent(),
                destination=self.user,
                content=MessageContent(text=algorithm_description, task=task),
                render_mode=RenderMode.LIST_UPDATED
            )
            await self.bot.sendMessage(message)

    async def runEventLoop(self) -> None:

        self.statiticsProvider.initialize()

        with self._lock:
            await self.checkFilteredListChanges()

        # Reads every message received by the bot
        messages = await self.bot.getMessageUpdates()

        with self._lock:
            if not messages:  # If the list is empty
                return

            for message in messages:
                isLastIteration = message == messages[-1]
                if self.chatId == 0:  # TODO: esta policy debe moverse a telegram
                    self.chatId = int(message.source.id)
                if message.source.id == str(self.chatId):
                    await self.processMessage(message, isLastIteration)

    # Each command must be made into an object and injected into this class
    async def listCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /list
        This command lists the tasks in the current view.
        - It shows a list of tasks and a shortcut command to select them.
        - If there's more than one page, it will show the first page.
        - You can use /next and /previous to navigate through the pages.
        - You can use /task_ to select a task.
        - Tasks are filtered according to the selected /filter strategy
        - Tasks are sorted according the selected /heuristic strategy
        """
        self._taskListManager.reset_pagination()
        await self.sendTaskList(reqId=reqId)

    async def nextCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /next
        This command shows the next page of tasks.
        It only works if there's more than one page.
        """
        self._taskListManager.next_page()
        if expectAnswer:
            await self.sendTaskList(reqId=reqId)

    async def previousCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /previous
        This command shows the previous page of tasks.
        It only works if there's more than one page.
        """
        self._taskListManager.prior_page()
        if expectAnswer:
            await self.sendTaskList(reqId=reqId)

    async def selectTaskCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /task_[task_number]
        This command selects a task to show more information.
        You can use /info to show detailed information about the selected task.
        Once a task is selected, it can be manipulated with other commands.
        """
        self._taskListManager.select_task(messageText)
        selectedTask = self._taskListManager.selected_task
        self._logger.debug(f"Selected task: {selectedTask.getDescription() if isinstance(selectedTask, ITaskModel) else 'None'}")

        if expectAnswer and isinstance(selectedTask, ITaskModel):
            await self.sendTaskInformation(selectedTask, reqId=reqId)

    async def taskInfoCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /info
        This command shows detailed information about the selected task.
        It shows all the information available for the selected task:
        - Description: Main text describing the task
        - Context: Category or project the task belongs to
        - Start: When the task becomes available
        - Due: When the task needs to be completed by
        - Total Cost: Estimated time/effort required to complete
        - Remaining Cost: Effort that still needs to be invested
        - Severity: Priority or importance level of the task
        - Heuristic values: Calculated metrics for task prioritization
        - Metadata: Task representation in the system
        """
        selectedTask = self._taskListManager.selected_task
        if selectedTask is not None:
            await self.sendTaskInformation(selectedTask, True, reqId=reqId)
        else:
            await self.__send_raw_text_message("No task selected.", reqId=reqId)

    async def helpCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command Manual
        This manual will show what features are available and how to use them.
        send /help command_name to get more information about a specific command.

        ## Task Listing
        - /list - List tasks in the current view
        - /next - Show the next page of tasks
        - /previous - Show the previous page of tasks
        - /agenda - Show the tasks for today
        - /heuristic - List heuristic options
        - /heuristic_[heuristic] - Select a heuristic
        - /filter - List filter options
        - /filter_[filter] - Select a filter
        - /algorithm - Show the current algorithm used for task sorting
        - /algorithm_[algorithm] - Select an algorithm for task sorting

        ## Task Querying
        - /task_[task_number] - Select a task to show more information
        - /info - Show detailed information about the selected task
        - /search [search terms] - Search for tasks

        ## Task Manipulation
        - /done - Mark the selected task as done
        - /set [parameter] [value] - Set a parameter of the selected task
        - /new [description] - Create a new task
        - /schedule [expected work per day (optional)] - Reschedule the selected task
        - /work [time] - Add work to the selected task
        - /snooze [time] - Snooze the selected task

        ## Project Management
        - /project [command] - Manage projects

        ## Data Management
        - /export [format] - Export tasks to a file
        - /import [format] - Import tasks from a file

        ## Other
        - /help - Show this help message
        - /stats - Show work done statistics
        - date - Time point format
        - time - Time diff format
        """
        helpMessage: list[str] = []

        args = messageText.split(" ")[1:]
        commandsStr = [command[0] for command in self.commands]
        printHelp = True
        if len(args) > 0:
            commandKey = f"/{args[0]}"
            printHelp = False
            if (commandKey in commandsStr):
                commandFunc = next((command[1] for command in self.commands if command[0] in commandKey), None)
                commandDoc = commandFunc.__doc__
                if isinstance(commandDoc, str):
                    for line in commandDoc:
                        helpMessage.append(line.strip())
            elif args[0] == "date":
                helpMessage.append("# Time point format")
                helpMessage.append("The time point format is YYYY-MM-DD or YYYY-MM-DDTHH:MM")
                helpMessage.append("You can use the following shortcuts:")
                helpMessage.append("- today: Current date")
                helpMessage.append("- tomorrow: Next day")
                helpMessage.append("- now: Current time")
                helpMessage.append("When using the time format, you can use the following:")
                helpMessage.append("- YYYY-MM-DDTHH:MM: Date and time")
                helpMessage.append("- YYYY-MM-DD: Date")
                helpMessage.append("Or concatenate time points with time diff by using ;")
                helpMessage.append("Example: 'today;+2h' will be today at 02:00 am")
            elif args[0] == "time":
                helpMessage.append("# Time diff format")
                helpMessage.append("The time duration format is [+|-][number][unit]")
                helpMessage.append("You can use the following units:")
                helpMessage.append("- m: minutes")
                helpMessage.append("- h: hours")
                helpMessage.append("- d: days")
                helpMessage.append("- w: weeks")
                helpMessage.append("- p: pomodoros (by omitting the unit)")
                helpMessage.append("You can concatenate time diffs by using ;")
                helpMessage.append("Example: '+1d;+2h' will be tomorrow at 02:00 am")
            else:
                printHelp = True

        if printHelp:
            helpCommandDoc = self.helpCommand.__doc__
            assert isinstance(helpCommandDoc, str)
            helpMessage.append(helpCommandDoc)

        await self.__send_raw_text_message("\n".join(helpMessage), reqId=reqId)

    async def heuristicListCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /heuristic
        This command lists the available heuristic options.
        Heuristics are used to sort the tasks in the list.
        The selected heuristic will be used to sort the tasks.
        """
        heuristic_list_content = self._taskListManager.get_heuristic_list()

        message: IMessage = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(anonObjectList=heuristic_list_content),
            render_mode=RenderMode.HEURISTIC_LIST
        )
        message.content.requestId = reqId

        await self.bot.sendMessage(message=message)

    async def algorithmListCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /algorithm
        This command lists the available algorithm options.
        Algorithms are used to sort the tasks in the list.
        The selected algorithm will be used to sort the tasks.
        """
        algorithm_list = self._taskListManager.get_algorithm_list()

        message: IMessage = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(anonObjectList=algorithm_list),
            render_mode=RenderMode.ALGORITHM_LIST
        )
        message.content.requestId = reqId

        await self.bot.sendMessage(message=message)

    async def raiseAlgorithmCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        arg = messageText.split(" ")[1:][0]
        if self._application_service is not None:
            try:
                result = await self._application_service.execute_operation_async(
                    "raise-event", OperationTarget("event", arg), {}, operation_id=None
                )
            except DomainError as error:
                await self.__send_raw_text_message(error.message, reqId=reqId)
                return
            self._taskListManager.update_taskList(self.taskProvider.getTaskList())
            affected_count = int(result.value or 0)
            self._logger.debug(f"Raised event '{arg}' affecting {affected_count} tasks.")
            await self.__send_raw_text_message(f"{affected_count} task affected.", reqId=reqId)
            return

        def raise_and_save() -> list[ITaskModel]:
            affected = self._taskListManager.raiseEvent(arg)
            for task in affected:
                self.taskProvider.saveTask(task)
            return affected

        affected = await self._run_legacy_mutation(raise_and_save)
        self._logger.debug(f"Raised event '{arg}' affecting {len(affected)} tasks.")

        await self.__send_raw_text_message(f"{len(affected)} task affected.", reqId=reqId)

    async def filterListCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /filter
        This command lists the available filter options.
        Filters are used to show only the tasks that match the criteria.
        The selected filter will be used to show the tasks.
        """
        filterListContent = self._taskListManager.get_filter_list()["filterList"]  # Should be a dict
        message = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(filterListDict=filterListContent),
            render_mode=RenderMode.FILTER_LIST
        )
        message.content.requestId = reqId

        await self.bot.sendMessage(message=message)

    async def heuristicSelectionCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /heuristic_[heuristic]
        This command selects a heuristic to sort the tasks.
        The heuristic will be used to sort the tasks.
        """
        self._taskListManager.select_heuristic(messageText)
        if expectAnswer:
            await self.sendTaskList(reqId=reqId)

    async def algorithmSelectionCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /algorithm_[algorithm]
        This command selects an algorithm to sort the tasks.
        The algorithm will be used to sort the tasks.
        """
        self._taskListManager.select_algorithm(messageText)
        if expectAnswer:
            await self.sendTaskList(reqId=reqId)

    async def filterSelectionCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /filter_[filter]
        This command toggles a filter to show only the tasks that match the criteria.
        The filter will be used to show the tasks.
        """
        self._taskListManager.select_filter(messageText)
        if expectAnswer:
            await self.sendTaskList(reqId=reqId)

    async def doneCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /done
        This command marks the selected task as done.
        The task will be marked as completed and removed from the list.
        """
        selected_task = self._taskListManager.selected_task
        if selected_task is not None:
            if self._application_service is not None:
                task_id = selected_task.getTaskUID()
                try:
                    result = await self._application_service.execute_operation_async(
                        "complete-task", OperationTarget("task", task_id), {}, operation_id=None
                    )
                except DomainError as error:
                    await self.__send_raw_text_message(error.message, reqId=reqId)
                    return
                self._taskListManager.update_taskList(self.taskProvider.getTaskList())
                task = result.value
                self._logger.debug(f"Task '{task.getDescription()}' marked as done.")
                if expectAnswer:
                    await self.sendTaskList(reqId=reqId)
                return

            def complete_and_save() -> ITaskModel:
                selected_task.setStatus("x")
                event = selected_task.getEventRaised()
                if isinstance(event, str):
                    for affected_task in self._taskListManager.raiseEvent(event):
                        if affected_task is not selected_task:
                            self.taskProvider.saveTask(affected_task)
                self.taskProvider.saveTask(selected_task)
                return selected_task

            task = await self._run_legacy_mutation(complete_and_save)
            self._logger.debug(f"Task '{task.getDescription()}' marked as done.")
            if expectAnswer:
                await self.sendTaskList(reqId=reqId)
        else:
            await self.__send_raw_text_message("no task selected.", reqId=reqId)

    async def setCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /set [parameter] [value]
        This command sets a parameter of the selected task.
        You can set the following parameters:
        - description: Main text describing the task
        - context: Category or project the task belongs to
        - start: When the task becomes available
        - due: When the task needs to be completed by
        - total_cost: Estimated time/effort required to complete
        - effort_invested: Effort that has been invested
        - calm: Flag to indicate if the task is calm or not
        The value of the parameter must be provided.
        ## Value types
        Type of values: text, date, time, number, boolean
        Text: Any text value
        Date: see /help date
        Time: /help time
        Number: Any number value
        Boolean: true or false
        """
        selected_task = self._taskListManager.selected_task
        if selected_task is not None:
            if self._application_service is not None:
                parts = messageText.split(" ", 2)
                if len(parts) < 3:
                    await self.__send_raw_text_message("A parameter and value are required.", reqId=reqId)
                    return
                supplied_name, value = parts[1], parts[2]
                field_names = (
                    "description", "context", "start", "due", "severity",
                    "total_cost", "effort_invested", "calm", "waited", "raised",
                )
                field_name = next((name for name in field_names if name.startswith(supplied_name)), None)
                if field_name is None:
                    await self.__send_raw_text_message(
                        "Invalid task field.", reqId=reqId
                    )
                    return
                target = OperationTarget("task", selected_task.getTaskUID())
                parameters: dict[str, Any]
                if field_name == "effort_invested":
                    parameters = {"effort_delta": value}
                else:
                    if field_name == "calm":
                        if value.casefold() not in ("true", "false"):
                            await self.__send_raw_text_message("calm must be true or false.", reqId=reqId)
                            return
                        field_value: Any = value.casefold() == "true"
                    elif field_name in ("waited", "raised") and value.casefold() == "null":
                        field_value = None
                    else:
                        field_value = value
                    parameters = {"changes": {field_name: field_value}}
                try:
                    result = await self._application_service.execute_operation_async(
                        "edit-task", target, parameters, operation_id=None
                    )
                except DomainError as error:
                    await self.__send_raw_text_message(error.message, reqId=reqId)
                    return
                task = result.value
                self._taskListManager.update_taskList(self.taskProvider.getTaskList())
                self._logger.debug(f"Task '{task.getDescription()}' updated through domain service.")
                if expectAnswer:
                    await self.sendTaskInformation(task, reqId=reqId)
                return
            params = messageText.split(" ")[1:]
            if len(params) < 2:
                params[0] = "help"
                params[1] = "me"
            parameter = params[0]
            value = " ".join(params[1:]) if len(params) > 2 else params[1]
            field_names = (
                "description", "context", "start", "due", "severity",
                "total_cost", "effort_invested", "calm", "waited", "raised",
            )
            field_name = next((name for name in field_names if name.startswith(parameter)), None)
            if field_name is None:
                await self.processSetParam(selected_task, parameter, value, reqId=reqId)
                return
            if field_name == "context" and not any(
                value.startswith(category["prefix"]) for category in self._categories
            ):
                error_message = (
                    f"Invalid context {value}\nvalid contexts would be: "
                    f"{', '.join([category['prefix'] for category in self._categories])}"
                )
                await self.__send_raw_text_message(error_message, reqId=reqId)
                return

            def set_and_save() -> ITaskModel:
                self._apply_legacy_set_value(selected_task, field_name, value)
                self.taskProvider.saveTask(selected_task)
                return selected_task

            task = await self._run_legacy_mutation(set_and_save)
            self._logger.debug(f"Task '{task.getDescription()}' set parameter '{parameter}' to '{value}'.")
            if expectAnswer:
                await self.sendTaskInformation(task, reqId=reqId)
        else:
            await self.__send_raw_text_message("no task selected.", reqId=reqId)

    async def newCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /new [description](;[context];[total_cost])
        This command creates a new task with the provided description.
        The task will be added to the list and can be selected.
        You can optionalyy provide a context and total cost for the task.
        The context is the category or project the task belongs to.
        The total cost is the estimated time/effort required to complete.
        The context and total cost must be separated by a semicolon.
        """
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            extendedParams = " ".join(params).split(";")

            if self._application_service is not None:
                operation_parameters: dict[str, Any] = {"description": extendedParams[0]}
                if len(extendedParams) == 3:
                    operation_parameters["context"] = extendedParams[1]
                    operation_parameters["total_cost"] = extendedParams[2]
                elif len(extendedParams) != 1:
                    operation_parameters["description"] = " ".join(params)
                try:
                    result = await self._application_service.execute_operation_async(
                        "create-task", OperationTarget("tasks"), operation_parameters, operation_id=None
                    )
                except DomainError as error:
                    await self.__send_raw_text_message(error.message, reqId=reqId)
                    return
                selected_task = result.value
                self._taskListManager.selected_task = selected_task
                self._taskListManager.update_taskList(self.taskProvider.getTaskList())
                self._logger.debug(f"Task '{selected_task.getDescription()}' created.")
                if expectAnswer:
                    await self.sendTaskInformation(selected_task, reqId=reqId)
                return

            def create_and_save() -> ITaskModel:
                if len(extendedParams) == 3:
                    task = self.taskProvider.createDefaultTask(extendedParams[0])
                    task.setContext(extendedParams[1])
                    task.setTotalCost(TimeAmount(extendedParams[2]))
                else:
                    task = self.taskProvider.createDefaultTask(" ".join(params))
                self.taskProvider.saveTask(task)
                return task

            selected_task = await self._run_legacy_mutation(create_and_save)
            self._taskListManager.selected_task = selected_task
            self._taskListManager.add_task(selected_task)
            self._logger.debug(f"Task '{selected_task.getDescription()}' created.")
            if expectAnswer:
                await self.sendTaskInformation(selected_task, reqId=reqId)
        else:
            await self.__send_raw_text_message("no description provided.", reqId=reqId)

    async def scheduleCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /schedule [expected work per day (optional)]
        This command reschedules the selected task.
        You can provide the expected work per day to distribute the effort.
        The task due date will be rescheduled according to the provided value.
        If no value is provided, task severity will be adjusted, keeping the same due date.
        If the required effort per day would result in severity < 1, the task will be automatically split into multiple parts.
        """
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            if self._application_service is not None:
                effort = params[-1] if params else ""
                target = OperationTarget("task", selected_task.getTaskUID())
                try:
                    result = await self._application_service.execute_operation_async(
                        "schedule-task", target, {"effort_per_day": effort}, operation_id=None
                    )
                except DomainError as error:
                    await self.__send_raw_text_message(error.message, reqId=reqId)
                    return
                resulting_tasks = list(result.value)
                self._taskListManager.update_taskList(self.taskProvider.getTaskList())
                if len(resulting_tasks) > 1 and expectAnswer:
                    split_count = len(resulting_tasks)
                    original_description = resulting_tasks[0].getDescription().replace(f" 1/{split_count}", "")
                    await self.__send_raw_text_message(
                        f"Task '{original_description}' was split into {split_count} parts due to high effort per day."
                    )
                self._logger.debug(f"Task '{selected_task.getDescription()}' was rescheduled.")
                if expectAnswer:
                    await self.sendTaskInformation(resulting_tasks[0], reqId=reqId)
                return
            # Enhanced scheduling and all resulting writes share one business turn.
            effort = params[-1] if params else ""

            def schedule_and_save() -> list[ITaskModel]:
                resulting = self.scheduling.schedule(selected_task, effort)
                for task in resulting:
                    self.taskProvider.saveTask(task)
                return resulting

            resulting_tasks = await self._run_legacy_mutation(schedule_and_save)
            if len(resulting_tasks) > 1:
                for task in resulting_tasks:
                    if task is not selected_task:
                        self._taskListManager.add_task(task)
                
                if expectAnswer:
                    split_count = len(resulting_tasks)
                    original_description = resulting_tasks[0].getDescription().replace(f" 1/{split_count}", "")
                    await self.__send_raw_text_message(
                        f"Task '{original_description}' was split into {split_count} parts due to high effort per day.",
                        reqId=None
                    )
                    # Show the first split task
                    await self.sendTaskInformation(resulting_tasks[0], reqId=reqId)

                self._logger.debug(f"Task '{selected_task.getDescription()}' was rescheduled and split into {len(resulting_tasks)} parts.")
            else:
                # Normal single task scheduling
                self._logger.debug(f"Task '{selected_task.getDescription()}' was rescheduled.")
                if expectAnswer:
                    await self.sendTaskInformation(resulting_tasks[0], reqId=reqId)
        else:
            await self.__send_raw_text_message("no task provided.", reqId=reqId)

    async def workCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /work [time]
        This command adds work to the selected task.
        You can provide the time spent on the task.
        The task effort invested will be updated.
        """
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            if self._application_service is not None:
                if not params:
                    await self.__send_raw_text_message("A work duration is required.", reqId=reqId)
                    return
                try:
                    result = await self._application_service.execute_operation_async(
                        "record-work",
                        OperationTarget("task", selected_task.getTaskUID()),
                        {"duration": " ".join(params)},
                        operation_id=None,
                    )
                except DomainError as error:
                    await self.__send_raw_text_message(error.message, reqId=reqId)
                    return
                task = result.value
                self._taskListManager.update_taskList(self.taskProvider.getTaskList())
                self._logger.debug(f"Recorded work on task '{task.getDescription()}'.")
                if expectAnswer:
                    await self.sendTaskInformation(task, reqId=reqId)
                return
            work_units = TimeAmount(" ".join(params[0:]))
            date = datetime.datetime.now().date()

            def record_work_and_save() -> ITaskModel:
                selected_task.setInvestedEffort(selected_task.getInvestedEffort() + work_units)
                selected_task.setTotalCost(selected_task.getTotalCost() - work_units)
                self.taskProvider.saveTask(selected_task)
                self.statiticsProvider.doWork(date, work_units, selected_task)
                return selected_task

            task = await self._run_legacy_mutation(record_work_and_save)
            self._logger.debug(f"Added {str(work_units)} of work to task '{task.getDescription()}'.")
            if expectAnswer:
                await self.sendTaskInformation(task, reqId=reqId)
        else:
            await self.__send_raw_text_message("no task provided.", reqId=reqId)

    async def statsCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /stats
        This command shows work done statistics.
        It shows the work done today and the average work per day.
        """
        message = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(workloadStats=self._taskListManager.get_list_stats()),
            render_mode=RenderMode.TASK_STATS
        )
        message.content.requestId = reqId

        await self.bot.sendMessage(message=message)

    async def eventsCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /events
        This command shows event statistics for tasks.
        It displays overall event statistics including total events, raising/waiting tasks, and orphaned events.
        For each event, it shows which tasks are raising it, which tasks are waiting for it, and if it's orphaned.
        """
        events_content = self._taskListManager.getEventStatistics()
        
        message = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(eventsContent=events_content),
            render_mode=RenderMode.EVENTS
        )
        message.content.requestId = reqId

        await self.bot.sendMessage(message=message)

    async def snoozeCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /snooze [time]
        This command snoozes the selected task.
        You can provide the snooze time.
        The task start date will be updated.
        """
        params: list[str] | str = messageText.split(" ")[1:]
        if len(params) > 0:
            params = params[0]
        else:
            params = "5m"

        selected_task = self._taskListManager.selected_task
        if self._application_service is not None:
            if selected_task is None:
                await self.__send_raw_text_message("no task selected.", reqId=reqId)
                return
            try:
                result = await self._application_service.execute_operation_async(
                    "snooze-task",
                    OperationTarget("task", selected_task.getTaskUID()),
                    {"duration": params},
                    operation_id=None,
                )
            except DomainError as error:
                await self.__send_raw_text_message(error.message, reqId=reqId)
                return
            task = result.value
            self._taskListManager.update_taskList(self.taskProvider.getTaskList())
            if expectAnswer:
                await self.sendTaskInformation(task, reqId=reqId)
            return

        startParams = f"/set start now;+{params}"
        self._logger.debug(f"Snoozing task with params: {startParams}")
        await self.setCommand(startParams, reqId=reqId)

    async def exportCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /export [format]
        This command exports tasks to a file.
        You can provide the format of the exported file.
        The exported file will be sent to the chat.
        ## Supported formats
        json: JSON format
        ## Incoming formats
        ical: iCalendar format
        """
        formatIds: dict[str, str] = {
            "json": "json",
            # TODO: "ical": "ical"
        }

        messageArgs = messageText.split(" ")

        # message text contains the format of the export [json, ical]
        if len(messageArgs) > 1:
            exportFormat = messageArgs[1]
            selectedFormat = formatIds.get(exportFormat, "json")
        else:
            selectedFormat = "json"

        # get the exported data
        exportData: bytearray = self.taskProvider.exportTasks(selectedFormat)

        # send the exported data
        await self.bot.sendFile(chat_id=self.chatId, data=exportData)

    async def importCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /import [format]
        This command imports tasks from a file.
        You can provide the format of the imported file.
        The imported file will be used to update the task list.
        ## Supported formats
        json: JSON format
        ## Incoming formats
        ical: iCalendar format
        """
        formatIds: dict[str, str] = {
            "json": "json",
            # TODO: "ical": "ical"
        }

        messageArgs = messageText.split(" ")

        # message text contains the format of the import [json, ical]
        if len(messageArgs) > 1:
            importFormat = messageArgs[1]
            selectedFormat = formatIds.get(importFormat, "json")
        else:
            selectedFormat = "json"

        # get the imported data
        await self._run_legacy_mutation(lambda: self.taskProvider.importTasks(selectedFormat))
        self._taskListManager.update_taskList(self.taskProvider.getTaskList())
        await self.__send_raw_text_message(f"{selectedFormat} file imported", parse_mode="Markdown")
        await self.listCommand(messageText, expectAnswer, reqId)

    async def searchCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /search [search terms]
        This command searches for tasks.
        You can provide the search terms to filter the tasks.
        The tasks that match the search terms will be shown.
        If only one task matches, it will be selected.
        """
        # getting results
        searchTerms = messageText.split(" ")[1:]
        if self._application_service is not None:
            if not searchTerms:
                await self.__send_raw_text_message("No results found", reqId=reqId)
                return
            view = replace(
                self._current_view(),
                page=1,
                search=tuple(searchTerms),
            )
            try:
                result_content = self._application_service.query_tasks(view)
            except DomainError as error:
                await self.__send_raw_text_message(error.message, reqId=reqId)
                return
            search_results = result_content.tasks
            if len(search_results) == 1:
                try:
                    task = self._application_service.read_task(search_results[0].id)
                except DomainError as error:
                    await self.__send_raw_text_message(error.message, reqId=reqId)
                    return
                self._taskListManager.selected_task = task
                self._logger.debug(f"Search found one result, selecting task: {task.getDescription()}")
                await self.sendTaskInformation(task, reqId=reqId)
            elif search_results:
                result_content.interactive = False
                message = self.__messageBuilder.createOutboundMessage(
                    source=self.bot.getBotAgent(),
                    destination=self.user,
                    content=MessageContent(taskListContent=result_content),
                    render_mode=RenderMode.TASK_LIST,
                )
                message.content.requestId = reqId
                await self.bot.sendMessage(message=message)
            else:
                await self.__send_raw_text_message("No results found", reqId=reqId)
            return
        searchResultsManager = self._taskListManager.search_tasks(searchTerms)
        searchResults = searchResultsManager.filtered_task_list

        # processing results
        if len(searchResults) == 1:
            self._taskListManager.selected_task = searchResults[0]
            self._logger.debug(f"Search found one result, selecting task: {searchResults[0].getDescription()}")
            await self.sendTaskInformation(searchResults[0], reqId=reqId)
        elif len(searchResults) > 0:
            taskListContent = searchResultsManager.get_task_list_content()
            # TaskListContent is a dataclass - modify the interactive field directly
            taskListContent.interactive = False
            message = self.__messageBuilder.createOutboundMessage(
                source=self.bot.getBotAgent(),
                destination=self.user,
                content=MessageContent(taskListContent=taskListContent),
                render_mode=RenderMode.TASK_LIST
            )
            message.content.requestId = reqId

            await self.bot.sendMessage(message=message)
        else:
            await self.__send_raw_text_message("No results found", reqId=reqId)

    async def agendaCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /agenda
        This command shows the tasks for today.
        It shows the tasks that are due today.
        It will show the times they are available
        Finally it will show which non-urgent tasks are available next
        """
        if self._application_service is not None:
            try:
                agenda_content = self._application_service.read_agenda(AgendaQuery(TimePoint.today()))
            except DomainError as error:
                await self.__send_raw_text_message(error.message, reqId=reqId)
                return
        else:
            agenda_content = self._taskListManager.get_day_agenda_content(TimePoint.today(), self._categories)
        message = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(agendaContent=agenda_content),
            render_mode=RenderMode.TASK_AGENDA
        )
        message.content.requestId = reqId

        await self.bot.sendMessage(message=message)

    async def projectCommand(self, messageText: str = "", expectAnswer: bool = True, reqId: int | None = None) -> None:
        """
        # Command /project [command]
        This command manages projects.
        use /project help to get more information about project commands.
        """
        SUPPORTED_COMMANDS = ProjectCommands.values()
        messageArgs = messageText.split(" ")
        if len(messageArgs) < 2:
            await self.__send_raw_text_message("No project command provided", reqId=reqId)
            return

        command = messageArgs[1]
        if command not in SUPPORTED_COMMANDS:
            await self.__send_raw_text_message("Invalid project command", reqId=reqId)
            return

        def project_command() -> str:
            return self.__projectManager.process_command(command, messageArgs[2:])

        if self.mutation_coordinator is None:
            response = project_command()
        else:
            response = await self.mutation_coordinator.run_job_async(project_command)
        # TODO: technical debt, this should be returning a dict with enough info to build a message

        await self.__send_raw_text_message(response, reqId=reqId)

    async def processMessage(self, message: IMessage, isLastIteration: bool) -> None:
        """
        Process a single IMessage object, executing the appropriate command.

        Args:
            message: The IMessage object containing the command and arguments
            isLastIteration: A boolean indicating if this is the last message in the batch.
        """
        commands = self.commands

        # Extract the command and arguments from the IMessage
        command_name = f"/{message.content.text}"
        args = message.content.textList

        # Rebuild the message text in the format expected by the command handlers
        message_text = command_name
        if isinstance(args, list):
            for arg in args:
                assert isinstance(arg, str)
                message_text += " " + arg

        # Find the command handler that matches the command name
        command_handler = next((command[1] for command in commands if command_name.startswith(command[0])), self.helpCommand)

        # Execute the command
        await command_handler(message_text, isLastIteration, message.content.requestId)

    async def _run_legacy_mutation(self, callback: Callable[[], Any]) -> Any:
        """Run a synchronous legacy mutation without blocking the channel loop."""
        if self.mutation_coordinator is None:
            return callback()
        run_async = getattr(self.mutation_coordinator, "run_job_async", None)
        if callable(run_async):
            return await run_async(callback)
        return await asyncio.to_thread(self.mutation_coordinator.run_or_inline, callback)

    def processRelativeTimeSet(self, current: TimePoint, value: str) -> TimePoint:
        """
        Modifies a TimePoint by processing a chain of strings representing time diffs.
        it also has the following shortcuts:
        - now: Current time
        - today: Current date
        - tomorrow: Next day
        - HH:MM: Time of the day in which the pointer is set

        Params:
            current: The current time point.
            value: The string representing the time diff, several values can be concatenated by using a semicolon.

        Returns:
            The new time point.
        """
        values = value.split(";")
        currentTimePoint = current
        for value in values:
            if value == "now":
                currentTimePoint = currentTimePoint.now()
            elif value == "today":
                currentTimePoint = currentTimePoint.today()
            elif value == "tomorrow":
                currentTimePoint = currentTimePoint.tomorrow()
            elif value.find(":") > 0 and value.find("T") < 0:
                currentTimePoint = currentTimePoint.strip_time() + TimeAmount(value)
            else:
                currentTimePoint = currentTimePoint + TimeAmount(value)
        return currentTimePoint

    async def setDescriptionCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        task.setDescription(value)
        pass

    async def setContextCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        # check if context is equal to any of the categories prefixes throw error if not
        if any([value.startswith(category["prefix"]) for category in self._categories]):
            task.setContext(value)
        else:
            errorMessage = f"Invalid context {value}\nvalid contexts would be: {', '.join([category['prefix'] for category in self._categories])}"
            await self.__send_raw_text_message(errorMessage, reqId=reqId)

    async def setStartCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        """
        Sets the start date/time of a task.

        This method updates when a task becomes available based on the provided value.
        It supports both absolute and relative time formats:

        Params:
            task: The task model to update.
            value: The new start date/time value. Can be:
                - Relative format (starting with +/-, or keywords now/today/tomorrow)
                - Time format (HH:MM)
                - Absolute date format (YYYY-MM-DDTHH:MM)
                - Combined values separated by semicolons (e.g., "today;+2h")
        """
        if value.startswith("+") or value.startswith("-") or value.startswith("now") or value.startswith("today") or value.startswith("tomorrow") or (value.count(":") == 1 and value.count("T") == 0):
            start_timestamp = self.processRelativeTimeSet(task.getStart(), value)
            task.setStart(start_timestamp)
        else:
            start_datetime = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M')
            task.setStart(TimePoint(start_datetime))
        pass

    async def setDueCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        """
        Sets the due date/time of a task.

        This method updates the deadline by which a task should be completed based on the provided value.
        It supports both absolute and relative time formats:

        Params:
            task: The task model to update.
            value: The new due date/time value. Can be:
                - Relative format (starting with +/-, or keywords today/tomorrow)
                - Time format (HH:MM)
                - Absolute date format (YYYY-MM-DD)
                - Combined values separated by semicolons (e.g., "today;+2d")
        """
        if value.startswith("+") or value.startswith("-") or value.startswith("today") or value.startswith("tomorrow") or value.count(":") == 1:
            due_timestamp = self.processRelativeTimeSet(task.getDue(), value)
            task.setDue(due_timestamp)
        else:
            due_datetime = datetime.datetime.strptime(value, '%Y-%m-%d')
            task.setDue(TimePoint(due_datetime))
        pass

    async def setSeverityCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        task.setSeverity(float(value))
        pass

    async def setTotalCostCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        timeAmount = TimeAmount(value)
        task.setTotalCost(timeAmount)
        pass

    async def setEffortInvestedCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        newInvestedEffort = task.getInvestedEffort() + TimeAmount(value)
        newTotalCost = task.getTotalCost() - TimeAmount(value)
        task.setInvestedEffort(newInvestedEffort)
        task.setTotalCost(newTotalCost)
        pass

    async def setCalmCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        task.setCalm(value.upper().startswith("TRUE"))
        pass

    async def setWaitedCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        task.setEventWaited(value)
        pass

    async def setRaisedCommand(self, task: ITaskModel, value: str, reqId: int | None = None) -> None:
        task.setEventRaised(value)
        pass

    async def processSetParam(self, task: ITaskModel, param: str, value: str, reqId: int | None = None) -> None:

        commands: list[Tuple[str, Callable[[ITaskModel, str, int | None], Coroutine[Any, Any, Any]]]] = [
            ("description", self.setDescriptionCommand),
            ("context", self.setContextCommand),
            ("start", self.setStartCommand),
            ("due", self.setDueCommand),
            ("severity", self.setSeverityCommand),
            ("total_cost", self.setTotalCostCommand),
            ("effort_invested", self.setEffortInvestedCommand),
            ("calm", self.setCalmCommand),
            ("waited", self.setWaitedCommand),
            ("raised", self.setRaisedCommand)
        ]

        command = next((command for command in commands if command[0].startswith(param)), ("", None))[1]
        if command is not None:
            await command(task, value, reqId)
        else:
            errorMessage = f"Invalid parameter {param}\nvalid parameters would be: description, context, start, due, severity, total_cost, effort_invested, calm"
            await self.__send_raw_text_message(errorMessage, reqId=reqId)

    def _apply_legacy_set_value(self, task: ITaskModel, field_name: str, value: str) -> None:
        """Apply one already validated fallback field update synchronously."""
        if field_name == "description":
            task.setDescription(value)
        elif field_name == "context":
            task.setContext(value)
        elif field_name == "start":
            if value.startswith(("+", "-", "now", "today", "tomorrow")) or (value.count(":") == 1 and "T" not in value):
                task.setStart(self.processRelativeTimeSet(task.getStart(), value))
            else:
                task.setStart(TimePoint(datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M")))
        elif field_name == "due":
            if value.startswith(("+", "-", "today", "tomorrow")) or value.count(":") == 1:
                task.setDue(self.processRelativeTimeSet(task.getDue(), value))
            else:
                task.setDue(TimePoint(datetime.datetime.strptime(value, "%Y-%m-%d")))
        elif field_name == "severity":
            task.setSeverity(float(value))
        elif field_name == "total_cost":
            task.setTotalCost(TimeAmount(value))
        elif field_name == "effort_invested":
            task.setInvestedEffort(task.getInvestedEffort() + TimeAmount(value))
            task.setTotalCost(task.getTotalCost() - TimeAmount(value))
        elif field_name == "calm":
            task.setCalm(value.upper().startswith("TRUE"))
        elif field_name == "waited":
            task.setEventWaited(value)
        elif field_name == "raised":
            task.setEventRaised(value)
        else:
            raise ValueError(f"Unsupported task field: {field_name}")

    async def sendTaskList(self, interactive: bool = True, reqId: int | None = None) -> None:
        self._taskListManager.clear_selected_task()

        # Get structured task list content
        if self._application_service is not None:
            try:
                task_list_content = self._application_service.query_tasks(self._current_view())
            except DomainError as error:
                await self.__send_raw_text_message(error.message, reqId=reqId)
                return
        else:
            task_list_content = self._taskListManager.get_task_list_content()
        task_list_content.interactive = interactive

        # Create a structured message
        message = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(taskListContent=task_list_content),
            render_mode=RenderMode.TASK_LIST
        )
        message.content.requestId = reqId

        # Send the structured message
        await self.bot.sendMessage(message=message)

    async def sendTaskInformation(self, task: ITaskModel, extended: bool = False, reqId: int | None = None) -> None:
        # Get structured task information
        if self._application_service is not None:
            try:
                task_info = self._application_service.read_task_information(task.getTaskUID(), extended=extended)
            except DomainError as error:
                await self.__send_raw_text_message(error.message, reqId=reqId)
                return
        else:
            task_info = self._taskListManager.get_task_information(task, self.taskProvider, extended)

        # Create a structured message with the TASK_INFORMATION render mode
        message = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(taskInformation=task_info),
            render_mode=RenderMode.TASK_INFORMATION
        )
        message.content.requestId = reqId

        # Send the structured message
        await self.bot.sendMessage(message=message)

    async def __send_raw_text_message(self, text: str, parse_mode: str = "Markdown", reqId: int | None = None) -> None:
        """
        Private helper method to send raw text messages using the structured message approach.

        Args:
            text: The text content to send
            parse_mode: Optional formatting mode (e.g., "Markdown", "HTML")
        """
        message: IMessage = self.__messageBuilder.createOutboundMessage(
            source=self.bot.getBotAgent(),
            destination=self.user,
            content=MessageContent(text=text),
            render_mode=RenderMode.RAW_TEXT
        )

        message.content.requestId = reqId
        await self.bot.sendMessage(message=message)

    def _current_view(self) -> TaskView:
        current_view = getattr(self._taskListManager, "current_view", None)
        if callable(current_view):
            view = current_view()
            return view if isinstance(view, TaskView) else TaskView()
        return TaskView()
