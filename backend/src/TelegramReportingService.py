"""
TelegramReportingService
"""

import asyncio
import threading
import datetime

from time import sleep as sleepSync
from typing import List, Coroutine, Any, Tuple

from .Interfaces.IProjectManager import IProjectManager, ProjectCommands
from .Interfaces.ITaskListManager import ITaskListManager
from .Interfaces.IReportingService import IReportingService
from .Interfaces.ITaskProvider import ITaskProvider
from .Interfaces.ITaskModel import ITaskModel
from .Interfaces.IScheduling import IScheduling
from .Interfaces.IStatisticsService import IStatisticsService
from .wrappers.interfaces.IUserCommService import IUserCommService
from .wrappers.TimeManagement import TimeAmount, TimePoint


class TelegramReportingService(IReportingService):

    def __init__(self, bot: IUserCommService, taskProvider: ITaskProvider, scheduling: IScheduling, statiticsProvider: IStatisticsService, task_list_manager: ITaskListManager, categories: list[dict], projectManager: IProjectManager, chatId: int = 0):
        # Private Attributes
        self.run = True
        self.bot = bot
        self.chatId = chatId
        self.taskProvider = taskProvider
        self.scheduling = scheduling
        self.statiticsProvider = statiticsProvider
        self.__projectManager = projectManager

        self.__lastModelList: List[ITaskModel] = []
        self._updateFlag = False

        self._taskListManager = task_list_manager

        self._lastError = "Event loop initialized"
        self._lock = threading.Lock()

        self._categories = categories

        self.commands: List[Tuple[str, Coroutine[Any, Any, None]]] = [
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
            ("/snooze", self.snoozeCommand),
            ("/export", self.exportCommand),
            ("/import", self.importCommand),
            ("/search", self.searchCommand),
            ("/agenda", self.agendaCommand),
            ("/project", self.projectCommand)
        ]
        pass

    def dispose(self):
        self.run = False
        self.bot.shutdown()
        self.taskProvider.dispose()
        pass

    def onTaskListUpdated(self):
        with self._lock:
            self._updateFlag = True
            self._taskListManager.update_taskList(self.taskProvider.getTaskList())

    def listenForEvents(self):
        self.taskProvider.registerTaskListUpdatedCallback(self.onTaskListUpdated)
        self._taskListManager.update_taskList(self.taskProvider.getTaskList())
        errCount = 0
        while self.run:
            try:
                asyncio.run(self._listenForEvents())
                errCount = 0
            except Exception as e:
                self._lastError = f"Error: {repr(e)}"
                print(self._lastError)
                sleepSync(10)
                errCount += 1
                if errCount > 30:
                    print("stopping container")
                    self.run = False
                    break

    async def _listenForEvents(self):
        await self.bot.initialize()
        await self.bot.sendMessage(chat_id=self.chatId, text=self._lastError)
        while self.run:
            try:
                await self.runEventLoop()
            except Exception as e:
                try:
                    await self.bot.shutdown()
                except Exception as e:
                    print(f"Fatal error: {repr(e)} shutting down.")
                    self.run = False
                finally:
                    raise e

    def hasFilteredListChanged(self):
        filteredList = self._taskListManager.filtered_task_list
        if self.taskProvider.compare(self._taskListManager.filtered_task_list, self.__lastModelList):
            return False
        self.__lastModelList = filteredList
        return True

    async def checkFilteredListChanges(self):
        if self.chatId != 0 and self.hasFilteredListChanged():
            # Send the updated list
            nextTask = ""
            filteredList = self._taskListManager.filtered_task_list
            if len(filteredList) != 0:
                nextTask = f"\n\n/task_1: {filteredList[0].getDescription()}"
            self._taskListManager.reset_pagination()
            await self.bot.sendMessage(chat_id=self.chatId, text="Task /list updated" + nextTask)

    async def runEventLoop(self):

        self.statiticsProvider.initialize()

        with self._lock:
            await self.checkFilteredListChanges()

        # Reads every message received by the bot
        result = await self.bot.getMessageUpdates()

        with self._lock:
            if result is None:
                return

            if self.chatId == 0:
                self.chatId = result[0]
            elif result[0] == int(self.chatId):
                await self.processMessage(result[1])

    # Each command must be made into an object and injected into this class
    async def listCommand(self, messageText: str = "", expectAnswer: bool = True):
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
        await self.sendTaskList()

    async def nextCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /next
        This command shows the next page of tasks.
        It only works if there's more than one page.
        """
        self._taskListManager.next_page()
        if expectAnswer:
            await self.sendTaskList()

    async def previousCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /previous
        This command shows the previous page of tasks.
        It only works if there's more than one page.
        """
        self._taskListManager.prior_page()
        if expectAnswer:
            await self.sendTaskList()

    async def selectTaskCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /task_[task_number]
        This command selects a task to show more information.
        You can use /info to show detailed information about the selected task.
        Once a task is selected, it can be manipulated with other commands.
        """
        self._taskListManager.select_task(messageText)

        selectedTask: ITaskModel = self._taskListManager.selected_task
        if expectAnswer:
            await self.sendTaskInformation(selectedTask)

    async def taskInfoCommand(self, messageText: str = "", expectAnswer: bool = True):
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
            await self.sendTaskInformation(selectedTask, True)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def helpCommand(self, messageText: str = "", expectAnswer: bool = True):
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
                commandDoc = commandFunc.__doc__.splitlines()
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
            helpMessage.append(self.helpCommand.__doc__)

        await self.bot.sendMessage(chat_id=self.chatId, text="\n".join(helpMessage))

    async def heuristicListCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /heuristic
        This command lists the available heuristic options.
        Heuristics are used to sort the tasks in the list.
        The selected heuristic will be used to sort the tasks.
        """
        await self.bot.sendMessage(chat_id=self.chatId, text=self._taskListManager.get_heuristic_list())

    async def filterListCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /filter
        This command lists the available filter options.
        Filters are used to show only the tasks that match the criteria.
        The selected filter will be used to show the tasks.
        """
        filterList = self._taskListManager.get_filter_list()
        await self.bot.sendMessage(chat_id=self.chatId, text=filterList)

    async def heuristicSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /heuristic_[heuristic]
        This command selects a heuristic to sort the tasks.
        The heuristic will be used to sort the tasks.
        """
        self._taskListManager.select_heuristic(messageText)
        if expectAnswer:
            await self.sendTaskList()

    async def filterSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /filter_[filter]
        This command selects a filter to show only the tasks that match the criteria.
        The filter will be used to show the tasks.
        """
        self._taskListManager.select_filter(messageText)
        if expectAnswer:
            await self.sendTaskList()

    async def doneCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /done
        This command marks the selected task as done.
        The task will be marked as completed and removed from the list.
        """
        selected_task = self._taskListManager.selected_task
        if selected_task is not None:
            task = selected_task
            task.setStatus("x")
            self.taskProvider.saveTask(task)
            if expectAnswer:
                await self.sendTaskList()
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def setCommand(self, messageText: str = "", expectAnswer: bool = True):
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
            task = selected_task
            params = messageText.split(" ")[1:]
            if len(params) < 2:
                params[0] = "help"
                params[1] = "me"
            await self.processSetParam(task, params[0], " ".join(params[1:]) if len(params) > 2 else params[1])
            self.taskProvider.saveTask(task)
            if expectAnswer:
                await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def newCommand(self, messageText: str = "", expectAnswer: bool = True):
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

            if len(extendedParams) == 3:
                self._taskListManager.selected_task = self.taskProvider.createDefaultTask(extendedParams[0])
                selected_task = self._taskListManager.selected_task
                selected_task.setContext(extendedParams[1])
                selected_task.setTotalCost(TimeAmount(extendedParams[2]))
            else:
                self._taskListManager.selected_task = self.taskProvider.createDefaultTask(" ".join(params))
                selected_task = self._taskListManager.selected_task

            self.taskProvider.saveTask(selected_task)
            self._taskListManager.add_task(selected_task)
            if expectAnswer:
                await self.sendTaskInformation(selected_task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no description provided.")

    async def scheduleCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /schedule [expected work per day (optional)]
        This command reschedules the selected task.
        You can provide the expected work per day to distribute the effort.
        The task due date will be rescheduled according to the provided value.
        if no value is provided, task severity will be adjusted, keeping the same due date.
        """
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            self.scheduling.schedule(selected_task, params.pop() if len(params) > 0 else "")
            self.taskProvider.saveTask(selected_task)
            if expectAnswer:
                await self.sendTaskInformation(selected_task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def workCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /work [time]
        This command adds work to the selected task.
        You can provide the time spent on the task.
        The task effort invested will be updated.
        """
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            task = selected_task
            work_units = TimeAmount(" ".join(params[0:]))
            await self.processSetParam(task, "effort_invested", f"{str(work_units.as_pomodoros())}p")
            self.taskProvider.saveTask(task)
            date = datetime.datetime.now().date()
            self.statiticsProvider.doWork(date, work_units, task)
            if expectAnswer:
                await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def statsCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /stats
        This command shows work done statistics.
        It shows the work done today and the average work per day.
        """
        await self.bot.sendMessage(chat_id=self.chatId, text=self._taskListManager.get_list_stats(), parse_mode="Markdown")

    async def snoozeCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /snooze [time]
        This command snoozes the selected task.
        You can provide the snooze time.
        The task start date will be updated.
        """
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            params = params[0]
        else:
            params = "5m"

        startParams = f"/set start now;+{params}"
        await self.setCommand(startParams)

    async def exportCommand(self, messageText: str = "", expectAnswer: bool = True):
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
        formatIds: dict = {
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

    async def importCommand(self, messageText: str = "", expectAnswer: bool = True):
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
        formatIds: dict = {
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
        self.taskProvider.importTasks(selectedFormat)
        self._taskListManager.update_taskList(self.taskProvider.getTaskList())
        await self.bot.sendMessage(chat_id=self.chatId, text=f"{selectedFormat} file imported", parse_mode="Markdown")
        await self.listCommand(messageText, expectAnswer)

    async def searchCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /search [search terms]
        This command searches for tasks.
        You can provide the search terms to filter the tasks.
        The tasks that match the search terms will be shown.
        If only one task matches, it will be selected.
        """
        # getting results
        searchTerms = messageText.split(" ")[1:]
        searchResultsManager = self._taskListManager.search_tasks(searchTerms)
        searchResults = searchResultsManager.filtered_task_list

        # processing results
        if len(searchResults) == 1:
            self._taskListManager.selected_task = searchResults[0]
            await self.sendTaskInformation(searchResults[0])
        elif len(searchResults) > 0:
            taskListString = searchResultsManager.render_task_list_str(False)
            await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="No results found")

    async def agendaCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /agenda
        This command shows the tasks for today.
        It shows the tasks that are due today.
        It will show the times they are available
        Finally it will show which non-urgent tasks are available next
        """
        agenda = self._taskListManager.render_day_agenda(TimePoint.today(), self._categories)
        await self.bot.sendMessage(chat_id=self.chatId, text=agenda)

    async def projectCommand(self, messageText: str = "", expectAnswer: bool = True):
        """
        # Command /project [command]
        This command manages projects.
        use /project help to get more information about project commands.
        """
        SUPPORTED_COMMANDS = ProjectCommands.values()
        messageArgs = messageText.split(" ")
        if len(messageArgs) < 2:
            await self.bot.sendMessage(chat_id=self.chatId, text="No project command provided")
            return

        command = messageArgs[1]
        if command not in SUPPORTED_COMMANDS:
            await self.bot.sendMessage(chat_id=self.chatId, text="Invalid project command")
            return

        response = self.__projectManager.process_command(command, messageArgs[2:])
        await self.bot.sendMessage(chat_id=self.chatId, text=response)

    async def processMessage(self, messageText: str):
        commands: List[Tuple[str, Coroutine[Any, Any, None]]] = self.commands

        messageTextLines = messageText.strip().splitlines()

        # get first command that starts with the messageText
        iteration = 0
        for message in messageTextLines:
            command = next((command for command in commands if message.startswith(command[0])), ("/help", self.helpCommand))[1]
            isLastIteration = iteration == len(messageTextLines) - 1
            await command(message, isLastIteration)
            iteration += 1

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
            elif value.find(":") > 0:
                currentTimePoint = currentTimePoint.strip_time() + TimeAmount(value)
            else:
                currentTimePoint = currentTimePoint + TimeAmount(value)
        return currentTimePoint

    async def setDescriptionCommand(self, task: ITaskModel, value: str):
        task.setDescription(value)
        pass

    async def setContextCommand(self, task: ITaskModel, value: str):
        # check if context is equal to any of the categories prefixes throw error if not
        if any([value.startswith(category["prefix"]) for category in self._categories]):
            task.setContext(value)
        else:
            errorMessage = f"Invalid context {value}\nvalid contexts would be: {', '.join([category['prefix'] for category in self._categories])}"
            await self.bot.sendMessage(chat_id=self.chatId, text=errorMessage)

    async def setStartCommand(self, task: ITaskModel, value: str):
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
        if value.startswith("+") or value.startswith("-") or value.startswith("now") or value.startswith("today") or value.startswith("tomorrow") or value.count(":") == 1:
            start_timestamp = self.processRelativeTimeSet(task.getStart(), value)
            task.setStart(start_timestamp)
        else:
            start_datetime = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M')
            task.setStart(TimePoint(start_datetime))
        pass

    async def setDueCommand(self, task: ITaskModel, value: str):
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

    async def setSeverityCommand(self, task: ITaskModel, value: str):
        task.setSeverity(float(value))
        pass

    async def setTotalCostCommand(self, task: ITaskModel, value: str):
        timeAmount = TimeAmount(value)
        task.setTotalCost(timeAmount)
        pass

    async def setEffortInvestedCommand(self, task: ITaskModel, value: str):
        newInvestedEffort = task.getInvestedEffort() + TimeAmount(value)
        newTotalCost = task.getTotalCost() - TimeAmount(value)
        task.setInvestedEffort(newInvestedEffort)
        task.setTotalCost(newTotalCost)
        pass

    async def setCalmCommand(self, task: ITaskModel, value: str):
        task.setCalm(value.upper().startswith("TRUE"))
        pass

    async def processSetParam(self, task: ITaskModel, param: str, value: str):

        commands: list[(str, Coroutine[Any, Any, None])] = [
            ("description", self.setDescriptionCommand),
            ("context", self.setContextCommand),
            ("start", self.setStartCommand),
            ("due", self.setDueCommand),
            ("severity", self.setSeverityCommand),
            ("total_cost", self.setTotalCostCommand),
            ("effort_invested", self.setEffortInvestedCommand),
            ("calm", self.setCalmCommand),
        ]

        command = next((command for command in commands if command[0].startswith(param)), ("", None))[1]
        if command is not None:
            await command(task, value)
        else:
            errorMessage = f"Invalid parameter {param}\nvalid parameters would be: description, context, start, due, severity, total_cost, effort_invested, calm"
            await self.bot.sendMessage(chat_id=self.chatId, text=errorMessage)

    async def sendTaskList(self, interactive: bool = True):
        self._taskListManager.clear_selected_task()

        taskListString = self._taskListManager.render_task_list_str(interactive)

        await self.bot.sendMessage(chat_id=self.chatId, text=taskListString)
        pass

    async def sendTaskInformation(self, task: ITaskModel, extended: bool = False):
        taskInformation = self._taskListManager.render_task_information(task, self.taskProvider, extended)

        await self.bot.sendMessage(chat_id=self.chatId, text=taskInformation, parse_mode="HTML")
