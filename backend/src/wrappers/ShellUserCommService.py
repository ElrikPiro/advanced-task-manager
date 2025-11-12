from src.Interfaces.ITaskModel import ITaskModel
from src.Utils import AgendaContent, ExtendedTaskInformation, FilterEntry, TaskInformation, TaskListContent, WorkloadStats
from src.wrappers.Messaging import IAgent, IMessage, RenderMode, UserAgent, InboundMessage
from src.wrappers.interfaces.IUserCommService import IUserCommService


class ShellUserCommService(IUserCommService):
    def __init__(self, chatId: int, agent: IAgent) -> None:
        self.offset = 0
        self.chatId = int(chatId)
        self.agent = agent

        self.__renders = {
            RenderMode.TASK_LIST: self.__renderTaskList,
            RenderMode.RAW_TEXT: self.__renderRawText,
            RenderMode.LIST_UPDATED: self.__notifyListUpdated,
            RenderMode.HEURISTIC_LIST: self.__renderHeuristicList,
            RenderMode.ALGORITHM_LIST: self.__renderAlgorithmList,
            RenderMode.FILTER_LIST: self.__renderFilterList,
            RenderMode.TASK_STATS: self.__renderTaskStats,
            RenderMode.TASK_AGENDA: self.__renderTaskAgenda,
            RenderMode.TASK_INFORMATION: self.__renderTaskInformation
        }

    def __renderFilterList(self, message: IMessage) -> None:
        self.__botPrint("(Info) Filter List Render Mode")
        filter_list = message.content.get('filterList', [])
        if not isinstance(filter_list, list) or not filter_list:
            self.__botPrint("No filters available")
            return
        self.__botPrint("Available Filters:")
        for i, filter_info in enumerate(filter_list):
            if not isinstance(filter_info, FilterEntry):
                continue
            name = filter_info.name
            description = filter_info.description
            enabled = filter_info.enabled
            self.__botPrint(f" - (/filter_{i+1}) {name}: {description} [{'ENABLED' if enabled else 'DISABLED'}]")

    async def initialize(self) -> None:
        print("ShellUserBotService initialized")

    async def shutdown(self) -> None:
        print("ShellUserBotService shutdown")

    def __preprocessMessageText(self, text: str) -> str:
        if not text.startswith("/"):
            text = "/" + text

        return text

    async def __getMessageUpdates_legacy(self) -> tuple[int, str]:
        text = input(f"[User({self.chatId})]: ")
        self.offset += 1
        return (self.chatId, self.__preprocessMessageText(text))

    async def getMessageUpdates(self) -> list[IMessage]:
        """
        Gets messages from the user via the shell interface.
        Returns a list containing a single InboundMessage with the user's command and arguments.
        """
        # Get the raw input using the legacy method
        chat_id, message_text = await self.__getMessageUpdates_legacy()

        if not message_text:
            return []

        # Extract command and arguments
        parts = message_text.split()
        command = parts[0].strip('/')  # Remove the leading '/'
        args = parts[1:] if len(parts) > 1 else []

        # Create source and destination agents
        source_agent = UserAgent(str(chat_id))
        destination_agent = self.getBotAgent()

        # Create and return a list with the inbound message
        return [InboundMessage(source_agent, destination_agent, command, args)]

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        print(f"[bot -> {chat_id}]: File sent")
        # show the first 128 bytes of the file with a decoration that indicates the file size
        print(f"File content: {data[:128]}... ({len(data)} bytes)")

    def getBotAgent(self) -> IAgent:
        return self.agent

    def __renderTaskList(self, message: IMessage) -> None:
        self.__botPrint("(Info) Task List Render Mode")
        
        content = message.content.get("taskListContent", None)
        if not isinstance(content, TaskListContent):
            raise Exception("Invalid output message")
        
        algorithm_name = content.algorithm_name
        algorithm_desc = content.algorithm_desc
        sort_heuristic = content.sort_heuristic
        tasks = content.tasks

        # Print the algorithm details as a header
        print(f"Algorithm: {algorithm_name}\nDescription: {algorithm_desc}\nSort Heuristic: {sort_heuristic}\n")
        print("Tasks:")
        for task in tasks:
            task_id = task.id
            task_desc = task.description
            task_context = task.context
            print(f"  - Task ID: {task_id}, Description: {task_desc}, Context: {task_context}")

    def __renderRawText(self, message: IMessage) -> None:
        self.__botPrint("(Info) Raw Text Render Mode")
        self.__botPrint(str(message.content.get('text', 'No message')))

    def __notifyListUpdated(self, message: IMessage) -> None:
        self.__botPrint("(Info) List Updated Render Mode")

        algorithm_desc = message.content.get('algorithm_desc', 'No description provided')
        most_priority_task = message.content.get('task', None)  # id, description, context

        self.__botPrint(f"List updated with algorithm: {algorithm_desc}")
        if not isinstance(most_priority_task, ITaskModel):
            self.__botPrint("No tasks available")
            return

        self.__botPrint(f"Most priority task: {most_priority_task.getDescription()} (ID: /task_1, Context: {most_priority_task.getContext()})")

    def __renderHeuristicList(self, message: IMessage) -> None:
        self.__botPrint("(Info) Heuristic List Render Mode")
        heuristic_list = message.content.get('heuristicList', [])

        if not isinstance(heuristic_list, list) or not heuristic_list:
            self.__botPrint("No heuristics available")
            return

        self.__botPrint("Available Heuristics:")
        for i, heuristic in enumerate(heuristic_list):
            assert isinstance(heuristic, dict)
            self.__botPrint(f" - (/heuristic_{i+1}) {heuristic['name']}: {heuristic['description']}")

    def __renderAlgorithmList(self, message: IMessage) -> None:
        self.__botPrint("(Info) Algorithm List Render Mode")
        algorithm_list = message.content.get('algorithmList', [])

        if not isinstance(algorithm_list, list) or not algorithm_list:
            self.__botPrint("No algorithms available")
            return

        self.__botPrint("Available Algorithms:")
        for i, algorithm in enumerate(algorithm_list):
            assert isinstance(algorithm, dict)
            self.__botPrint(f" - (/algorithm_{i+1}) {algorithm['name']}: {algorithm['description']}")

    def __botPrint(self, text: str) -> None:
        print(f"[bot -> {self.chatId}]: {text}")

    def __renderTaskStats(self, message: IMessage) -> None:
        self.__botPrint("(Info) Task Stats Render Mode")
        
        # Import time management classes
        from src.wrappers.TimeManagement import TimePoint, TimeAmount
        
        # Extract data from the message
        stats = message.content.get("workloadStats")
        if not isinstance(stats, WorkloadStats):
            return
        
        workload = stats.workload
        remaining_effort = stats.remainingEffort
        heuristic_value = stats.maxHeuristic
        heuristic_name = stats.HeuristicName
        offender = stats.offender
        offender_max = stats.offenderMax
        work_done_log = stats.workDoneLog
        
        # Format and display workload statistics
        self.__botPrint("Work done in the last 7 days:")
        self.__botPrint("|    Date    | Work  Done |")
        self.__botPrint("|------------|------------|")
        
        # For shell display, we'll calculate this from the last 7 days of logs if available
        # (In a real implementation, this would need proper date filtering and aggregation)
        total_work = 0.0
        for i in range(min(7, len(work_done_log))):
            if i < len(work_done_log):
                entry = work_done_log[i]
                work_units = entry.work_units
                timestamp = entry.timestamp
                date_str = TimePoint.from_int(timestamp).__str__()
                self.__botPrint(f"| {date_str} |    {work_units}    |")
                total_work += work_units
        
        # Add average work done per day
        average_work = round(total_work / 7, 2) if work_done_log else 0
        self.__botPrint("|------------|------------|")
        self.__botPrint(f"|   Average  |    {average_work}    |")
        self.__botPrint("|------------|------------|")
        
        # Display workload statistics
        self.__botPrint("\nWorkload statistics:")
        self.__botPrint(f"current workload: {workload} per day")
        self.__botPrint(f"max Offender: '{offender}' with {offender_max} per day")
        self.__botPrint(f"total remaining effort: {remaining_effort}")
        self.__botPrint(f"max {heuristic_name}: {heuristic_value}")
        
        # Display work done log
        self.__botPrint("\nWork done log:")
        for entry in work_done_log:
            task = entry.task
            work_units = entry.work_units
            timestamp = entry.timestamp
            date_str = TimePoint.from_int(timestamp).__str__()
            time_amount = TimeAmount(f"{work_units}p")
            self.__botPrint(f"{date_str}: {time_amount} on {task}")
        
        self.__botPrint("\n/list - return back to the task list")
        
    def __renderTaskAgenda(self, message: IMessage) -> None:
        self.__botPrint("(Info) Task Agenda Render Mode")
        
        # Get content from message
        agenda = message.content.get("agendaContent")
        if not isinstance(agenda, AgendaContent):
            return

        date = agenda.date
        active_urgent_tasks = agenda.active_urgent_tasks
        planned_urgent_tasks = agenda.planned_urgent_tasks
        planned_tasks_by_date = agenda.planned_tasks_by_date
        other_tasks = agenda.other_tasks
        
        # Display the agenda header
        self.__botPrint(f"Agenda for {date}:\n")
        
        # Display active urgent tasks
        if active_urgent_tasks:
            self.__botPrint("# Active Urgent tasks:")
            for task in active_urgent_tasks:
                self.__botPrint(f"- {task.description} (Context: {task.context})")
            self.__botPrint("")
        
        # Display planned urgent tasks
        if planned_urgent_tasks:
            self.__botPrint("# Planned Urgent tasks:")
            for dateStr, tasks in planned_tasks_by_date.items():
                self.__botPrint(f"## {dateStr}")
                for task in tasks:
                    self.__botPrint(f"\t- {task.description} (Context: {task.context})")
            self.__botPrint("")
        
        # Display other tasks
        if other_tasks:
            self.__botPrint("# Other tasks:")
            for task in other_tasks:
                self.__botPrint(f"- {task.description} (Context: {task.context})")
            self.__botPrint("")
        
        self.__botPrint("/list - return back to the task list")
        
    def __renderTaskInformation(self, message: IMessage) -> None:
        self.__botPrint("(Info) Task Information Render Mode")
        
        # Extract task information from the message
        taskinfo = message.content.get("taskInfo")
        if not isinstance(taskinfo, TaskInformation):
            return

        task = taskinfo.task
        task_description = task.description
        task_context = task.context
        task_start_date = task.start
        task_due_date = task.due
        task_total_cost = task.total_cost
        task_remaining_cost = task.total_cost - task.effort_invested
        task_severity = task.heuristic_value
        # Unused for now, but may be needed in future enhancements
        # task_status = message.content.get('status', '')
        # task_calm = message.content.get('calm', False)
        
        # Format the basic task information
        self.__botPrint(f"Task: {task_description}")
        self.__botPrint(f"Context: {task_context}")
        self.__botPrint(f"Start Date: {task_start_date}")
        self.__botPrint(f"Due Date: {task_due_date}")
        self.__botPrint(f"Total Cost: {task_total_cost}")
        self.__botPrint(f"Remaining: {task_remaining_cost}")
        self.__botPrint(f"Severity: {task_severity}")
        
        # Include extended information if available
        extended_task_data = taskinfo.extended
        if isinstance(extended_task_data, ExtendedTaskInformation):
            self.__botPrint("\nHeuristic Values:")
            for heuristic in extended_task_data.heuristics:
                self.__botPrint(f"- {heuristic.name}: {heuristic.comment}")
        
            self.__botPrint("\nMetadata:")
            self.__botPrint(extended_task_data.metadata)
        
        # Add command options
        self.__botPrint("\n/list - Return to list")
        self.__botPrint("/done - Mark task as done")
        self.__botPrint("/set [param] [value] - Set task parameter")
        self.__botPrint("/work [work_units] - Invest work units in the task")
        self.__botPrint("/snooze - Snooze the task for 5 minutes")
        self.__botPrint("/info - Show extended information")

    async def sendMessage(self, message: IMessage) -> None:
        if message.type != "OutboundMessage":
            raise ValueError("Only OutboundMessage is supported in ShellUserCommService")

        render_mode = message.content.get('render_mode', int(RenderMode.RAW_TEXT))
        if isinstance(render_mode, int):
            self.__renders[render_mode](message)
