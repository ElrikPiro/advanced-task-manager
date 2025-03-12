"""
TelegramReportingService
"""

import asyncio
import threading
import datetime

from time import sleep as sleepSync
from typing import List, Coroutine, Any

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
        self._taskListManager.reset_pagination()
        await self.sendTaskList()

    async def nextCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.next_page()
        if expectAnswer:
            await self.sendTaskList()

    async def previousCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.prior_page()
        if expectAnswer:
            await self.sendTaskList()

    async def selectTaskCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.select_task(messageText)

        selectedTask: ITaskModel = self._taskListManager.selected_task
        if expectAnswer:
            await self.sendTaskInformation(selectedTask)

    async def taskInfoCommand(self, messageText: str = "", expectAnswer: bool = True):
        selectedTask = self._taskListManager.selected_task
        if selectedTask is not None:
            await self.sendTaskInformation(selectedTask, True)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task selected.")

    async def helpCommand(self, messageText: str = "", expectAnswer: bool = True):
        helpMessage: list[str] = []

        command = messageText.split(" ")[1:]
        printHelp = True
        if len(command) > 0:
            printHelp = False
            if command[0] == "list":
                helpMessage.append("# Command /list")
                helpMessage.append("This command lists the tasks in the current view.")
                helpMessage.append("It shows a list of tasks and a shortcut command to select them.")
                helpMessage.append("If there's more than one page, it will show the first page.")
                helpMessage.append("You can use /next and /previous to navigate through the pages.")
                helpMessage.append("You can use /task_ to select a task.")
                helpMessage.append("Tasks are filtered according to the selected /filter strategy")
                helpMessage.append("Tasks are sorted according the selected /heuristic strategy")
            elif command[0] == "next":
                helpMessage.append("# Command /next")
                helpMessage.append("This command shows the next page of tasks.")
                helpMessage.append("It only works if there's more than one page.")
            elif command[0] == "previous":
                helpMessage.append("# Command /previous")
                helpMessage.append("This command shows the previous page of tasks.")
                helpMessage.append("It only works if there's more than one page.")
            elif command[0] == "task_":
                helpMessage.append("# Command /task_ [task_number]")
                helpMessage.append("This command selects a task to show more information.")
                helpMessage.append("You can use /info to show detailed information about the selected task.")
                helpMessage.append("Once a task is selected, it can be manipulated with other commands.")
            elif command[0] == "info":
                helpMessage.append("# Command /info")
                helpMessage.append("This command shows detailed information about the selected task.")
                helpMessage.append("It shows all the information available for the selected task:")
                helpMessage.append("- Description: Main text describing the task")
                helpMessage.append("- Context: Category or project the task belongs to")
                helpMessage.append("- Start: When the task becomes available")
                helpMessage.append("- Due: When the task needs to be completed by")
                helpMessage.append("- Total Cost: Estimated time/effort required to complete")
                helpMessage.append("- Remaining Cost: Effort that still needs to be invested")
                helpMessage.append("- Severity: Priority or importance level of the task")
                helpMessage.append("- Heuristic values: Calculated metrics for task prioritization")
                helpMessage.append("- Metadata: Task representation in the system")
            elif command[0] == "heuristic":
                helpMessage.append("# Command /heuristic")
                helpMessage.append("This command lists the available heuristic options.")
                helpMessage.append("Heuristics are used to sort the tasks in the list.")
                helpMessage.append("The selected heuristic will be used to sort the tasks.")
            elif command[0] == "heuristic_":
                helpMessage.append("# Command /heuristic_[heuristic]")
                helpMessage.append("This command selects a heuristic to sort the tasks.")
                helpMessage.append("The heuristic will be used to sort the tasks.")
            elif command[0] == "filter":
                helpMessage.append("# Command /filter")
                helpMessage.append("This command lists the available filter options.")
                helpMessage.append("Filters are used to show only the tasks that match the criteria.")
                helpMessage.append("The selected filter will be used to show the tasks.")
            elif command[0] == "filter_":
                helpMessage.append("# Command /filter_[filter]")
                helpMessage.append("This command selects a filter to show only the tasks that match the criteria.")
                helpMessage.append("The filter will be used to show the tasks.")
            elif command[0] == "done":
                helpMessage.append("# Command /done")
                helpMessage.append("This command marks the selected task as done.")
                helpMessage.append("The task will be marked as completed and removed from the list.")
            elif command[0] == "set":
                helpMessage.append("# Command /set [parameter] [value]")
                helpMessage.append("This command sets a parameter of the selected task.")
                helpMessage.append("You can set the following parameters:")
                helpMessage.append("- description: Main text describing the task")
                helpMessage.append("- context: Category or project the task belongs to")
                helpMessage.append("- start: When the task becomes available")
                helpMessage.append("- due: When the task needs to be completed by")
                helpMessage.append("- total_cost: Estimated time/effort required to complete")
                helpMessage.append("- effort_invested: Effort that has been invested")
                helpMessage.append("- calm: Flag to indicate if the task is calm or not")
                helpMessage.append("The value of the parameter must be provided.")
                helpMessage.append("## Value types")
                helpMessage.append("Type of values: text, date, time, number, boolean")
                helpMessage.append("Text: Any text value")
                helpMessage.append("Date: see /help date")
                helpMessage.append("Time: /help time")
                helpMessage.append("Number: Any number value")
                helpMessage.append("Boolean: true or false")
            elif command[0] == "new":
                helpMessage.append("# Command /new [description](;[context];[total_cost])")
                helpMessage.append("This command creates a new task with the provided description.")
                helpMessage.append("The task will be added to the list and can be selected.")
                helpMessage.append("You can optionalyy provide a context and total cost for the task.")
                helpMessage.append("The context is the category or project the task belongs to.")
                helpMessage.append("The total cost is the estimated time/effort required to complete.")
                helpMessage.append("The context and total cost must be separated by a semicolon.")
            elif command[0] == "schedule":
                helpMessage.append("# Command /schedule [expected work per day (optional)]")
                helpMessage.append("This command reschedules the selected task.")
                helpMessage.append("You can provide the expected work per day to distribute the effort.")
                helpMessage.append("The task due date will be rescheduled according to the provided value.")
                helpMessage.append("if no value is provided, task severity will be adjusted, keeping the same due date.")
            elif command[0] == "work":
                helpMessage.append("# Command /work [time]")
                helpMessage.append("This command adds work to the selected task.")
                helpMessage.append("You can provide the time spent on the task.")
                helpMessage.append("The task effort invested will be updated.")
            elif command[0] == "stats":
                helpMessage.append("# Command /stats")
                helpMessage.append("This command shows work done statistics.")
                helpMessage.append("It shows the work done today and the average work per day.")
            elif command[0] == "snooze":
                helpMessage.append("# Command /snooze [time]")
                helpMessage.append("This command snoozes the selected task.")
                helpMessage.append("You can provide the snooze time.")
                helpMessage.append("The task start date will be updated.")
            elif command[0] == "export":
                helpMessage.append("# Command /export [format]")
                helpMessage.append("This command exports tasks to a file.")
                helpMessage.append("You can provide the format of the exported file.")
                helpMessage.append("The exported file will be sent to the chat.")
                helpMessage.append("## Supported formats")
                helpMessage.append("json: JSON format")
                # helpMessage.append("ical: iCalendar format")
            elif command[0] == "import":
                helpMessage.append("# Command /import [format]")
                helpMessage.append("This command imports tasks from a file.")
                helpMessage.append("You can provide the format of the imported file.")
                helpMessage.append("The imported file will be used to update the task list.")
                helpMessage.append("## Supported formats")
                helpMessage.append("json: JSON format")
                # helpMessage.append("ical: iCalendar format")
            elif command[0] == "search":
                helpMessage.append("# Command /search [search terms]")
                helpMessage.append("This command searches for tasks.")
                helpMessage.append("You can provide the search terms to filter the tasks.")
                helpMessage.append("The tasks that match the search terms will be shown.")
                helpMessage.append("If only one task matches, it will be selected.")
            elif command[0] == "agenda":
                helpMessage.append("# Command /agenda")
                helpMessage.append("This command shows the tasks for today.")
                helpMessage.append("It shows the tasks that are due today.")
                helpMessage.append("It will show the times they are available")
                helpMessage.append("Finally it will show which non-urgent tasks are available next")
            elif command[0] == "project":
                helpMessage.append("# Command /project [command]")
                helpMessage.append("This command manages projects.")
                helpMessage.append("use /project help to get more information about project commands.")
            elif command[0] == "help":
                helpMessage.append("# Command /help")
                helpMessage.append("This command shows the command manual.")
                helpMessage.append("It shows the available commands and how to use them.")
                helpMessage.append("You can use /help [command] to get more information about a specific command.")
            elif command[0] == "date":
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
            elif command[0] == "time":
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
            helpMessage.append("# Command Manual")
            helpMessage.append("This manual will show what features are available and how to use them.")
            helpMessage.append("send /help command_name to get more information about a specific command.")

            helpMessage.append("\n## Task Listing")
            helpMessage.append("- /list - List tasks in the current view")
            helpMessage.append("- /next - Show the next page of tasks")
            helpMessage.append("- /previous - Show the previous page of tasks")
            helpMessage.append("- /agenda - Show the tasks for today")
            helpMessage.append("- /heuristic - List heuristic options")
            helpMessage.append("- /heuristic_[heuristic] - Select a heuristic")
            helpMessage.append("- /filter - List filter options")
            helpMessage.append("- /filter_[filter] - Select a filter")

            helpMessage.append("\n## Task Querying")
            helpMessage.append("- /task_[task_number] - Select a task to show more information")
            helpMessage.append("- /info - Show detailed information about the selected task")
            helpMessage.append("- /search [search terms] - Search for tasks")

            helpMessage.append("\n## Task Manipulation")
            helpMessage.append("- /done - Mark the selected task as done")
            helpMessage.append("- /set [parameter] [value] - Set a parameter of the selected task")
            helpMessage.append("- /new [description] - Create a new task")
            helpMessage.append("- /schedule [expected work per day (optional)] - Reschedule the selected task")
            helpMessage.append("- /work [time] - Add work to the selected task")
            helpMessage.append("- /snooze [time] - Snooze the selected task")

            helpMessage.append("\n## Project Management")
            helpMessage.append("- /project [command] - Manage projects")

            helpMessage.append("\n## Data Management")
            helpMessage.append("- /export [format] - Export tasks to a file")
            helpMessage.append("- /import [format] - Import tasks from a file")

            helpMessage.append("\n## Other")
            helpMessage.append("- /help - Show this help message")
            helpMessage.append("- /stats - Show work done statistics")
            helpMessage.append("- date - Time point format")
            helpMessage.append("- time - Time diff format")

        await self.bot.sendMessage(chat_id=self.chatId, text="\n".join(helpMessage))

    async def heuristicListCommand(self, messageText: str = "", expectAnswer: bool = True):
        await self.bot.sendMessage(chat_id=self.chatId, text=self._taskListManager.get_heuristic_list())

    async def filterListCommand(self, messageText: str = "", expectAnswer: bool = True):
        filterList = self._taskListManager.get_filter_list()
        await self.bot.sendMessage(chat_id=self.chatId, text=filterList)

    async def heuristicSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.select_heuristic(messageText)
        if expectAnswer:
            await self.sendTaskList()

    async def filterSelectionCommand(self, messageText: str = "", expectAnswer: bool = True):
        self._taskListManager.select_filter(messageText)
        if expectAnswer:
            await self.sendTaskList()

    async def doneCommand(self, messageText: str = "", expectAnswer: bool = True):
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
        selected_task = self._taskListManager.selected_task
        params = messageText.split(" ")[1:]
        if selected_task is not None:
            task = selected_task
            work_units = TimeAmount(" ".join(params[0:]))
            await self.processSetParam(task, "effort_invested", str(work_units.as_pomodoros()))
            self.taskProvider.saveTask(task)
            date = datetime.datetime.now().date()
            self.statiticsProvider.doWork(date, work_units.as_pomodoros())
            if expectAnswer:
                await self.sendTaskInformation(task)
        else:
            await self.bot.sendMessage(chat_id=self.chatId, text="no task provided.")

    async def statsCommand(self, messageText: str = "", expectAnswer: bool = True):
        await self.bot.sendMessage(chat_id=self.chatId, text=self._taskListManager.get_list_stats(), parse_mode="Markdown")

    async def snoozeCommand(self, messageText: str = "", expectAnswer: bool = True):
        params = messageText.split(" ")[1:]
        if len(params) > 0:
            params = params[0]
        else:
            params = "5m"

        startParams = f"/set start now;+{params}"
        await self.setCommand(startParams)

    async def exportCommand(self, messageText: str = "", expectAnswer: bool = True):
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
        agenda = self._taskListManager.render_day_agenda(TimePoint.today(), self._categories)
        await self.bot.sendMessage(chat_id=self.chatId, text=agenda)

    async def projectCommand(self, messageText: str = "", expectAnswer: bool = True):
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
        commands: list[(str, Coroutine[Any, Any, None])] = [
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

        messageTextLines = messageText.strip().splitlines()

        # get first command that starts with the messageText
        iteration = 0
        for message in messageTextLines:
            command = next((command for command in commands if message.startswith(command[0])), ("/help", self.helpCommand))[1]
            isLastIteration = iteration == len(messageTextLines) - 1
            await command(message, isLastIteration)
            iteration += 1

    def processRelativeTimeSet(self, current: TimePoint, value: str) -> TimePoint:
        values = value.split(";")
        currentTimePoint = current
        for value in values:
            if value == "now":
                currentTimePoint = currentTimePoint.now()
            elif value == "today":
                currentTimePoint = currentTimePoint.today()
            elif value == "tomorrow":
                currentTimePoint = currentTimePoint.tomorrow()
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
        if value.startswith("+") or value.startswith("-") or value.startswith("now") or value.startswith("today") or value.startswith("tomorrow"):
            start_timestamp = self.processRelativeTimeSet(task.getStart(), value)
            task.setStart(start_timestamp)
        else:
            start_datetime = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M')
            task.setStart(TimePoint(start_datetime))
        pass

    async def setDueCommand(self, task: ITaskModel, value: str):
        if value.startswith("+") or value.startswith("-") or value.startswith("today") or value.startswith("tomorrow"):
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
