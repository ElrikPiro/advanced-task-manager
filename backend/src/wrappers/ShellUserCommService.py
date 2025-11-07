from src.wrappers.Messaging import IAgent, IMessage, RenderMode, UserAgent, InboundMessage
from src.wrappers.interfaces.IUserCommService import IUserCommService


class ShellUserCommService(IUserCommService):
    def __init__(self, chatId: int, agent: IAgent):
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

    def __renderFilterList(self, message: IMessage):
        self.__botPrint("(Info) Filter List Render Mode")
        filter_list = message.content.get('filterList', [])
        if not filter_list:
            self.__botPrint("No filters available")
            return
        self.__botPrint("Available Filters:")
        for i, filter_info in enumerate(filter_list):
            name = filter_info.get('name', f'Filter {i+1}')
            description = filter_info.get('description', '')
            enabled = filter_info.get('enabled', False)
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

    def getBotAgent(self):
        return self.agent

    def __renderTaskList(self, message: IMessage):
        self.__botPrint("(Info) Task List Render Mode")
        # TODO: Implement actual task list rendering logic
        algorithm_name = message.content.get('algorithm_name', 'Unknown Algorithm')
        algorithm_desc = message.content.get('algorithm_desc', 'No description provided')
        sort_heuristic = message.content.get('sort_heuristic', 'No heuristic provided')
        tasks = message.content.get('tasks', [])  # id, description, context

        # Print the algorithm details as a header
        print(f"Algorithm: {algorithm_name}\nDescription: {algorithm_desc}\nSort Heuristic: {sort_heuristic}\n")
        print("Tasks:")
        for task in tasks:
            task_id = task.get('id', 'Unknown ID')
            task_desc = task.get('description', 'No description')
            task_context = task.get('context', 'No context')
            print(f"  - Task ID: {task_id}, Description: {task_desc}, Context: {task_context}")

    def __renderRawText(self, message: IMessage):
        self.__botPrint("(Info) Raw Text Render Mode")
        self.__botPrint(message.content.get('text', 'No message'))

    def __notifyListUpdated(self, message: IMessage):
        self.__botPrint("(Info) List Updated Render Mode")

        algorithm_desc = message.content.get('algorithm_desc', 'No description provided')
        most_priority_task = message.content.get('task', None)  # id, description, context

        self.__botPrint(f"List updated with algorithm: {algorithm_desc}")
        if most_priority_task is None:
            self.__botPrint("No tasks available")
            return

        self.__botPrint(f"Most priority task: {most_priority_task['description']} (ID: {most_priority_task['id']}, Context: {most_priority_task['context']})")

    def __renderHeuristicList(self, message: IMessage):
        self.__botPrint("(Info) Heuristic List Render Mode")
        heuristic_list = message.content.get('heuristicList', [])

        if not heuristic_list:
            self.__botPrint("No heuristics available")
            return

        self.__botPrint("Available Heuristics:")
        for i, heuristic in enumerate(heuristic_list):
            self.__botPrint(f" - (/heuristic_{i+1}) {heuristic['name']}: {heuristic['description']}")

    def __renderAlgorithmList(self, message: IMessage):
        self.__botPrint("(Info) Algorithm List Render Mode")
        algorithm_list = message.content.get('algorithmList', [])

        if not algorithm_list:
            self.__botPrint("No algorithms available")
            return

        self.__botPrint("Available Algorithms:")
        for i, algorithm in enumerate(algorithm_list):
            self.__botPrint(f" - (/algorithm_{i+1}) {algorithm['name']}: {algorithm['description']}")

    def __botPrint(self, text: str):
        print(f"[bot -> {self.chatId}]: {text}")

    def __renderTaskStats(self, message: IMessage):
        self.__botPrint("(Info) Task Stats Render Mode")
        
        # Import time management classes
        from src.wrappers.TimeManagement import TimePoint, TimeAmount
        
        # Extract data from the message
        workload = message.content.get('workload', "0p")
        remaining_effort = message.content.get('remaining_effort', "0p")
        heuristic_value = message.content.get('heuristic_value', "0")
        heuristic_name = message.content.get('heuristic_name', "Unknown")
        offender = message.content.get('offender', "None")
        offender_max = message.content.get('offender_max', "0p")
        work_done_log = message.content.get('work_done_log', [])
        
        # Format and display workload statistics
        self.__botPrint("Work done in the last 7 days:")
        self.__botPrint("|    Date    | Work  Done |")
        self.__botPrint("|------------|------------|")
        
        # For shell display, we'll calculate this from the last 7 days of logs if available
        # (In a real implementation, this would need proper date filtering and aggregation)
        total_work = 0
        for i in range(min(7, len(work_done_log))):
            if i < len(work_done_log):
                entry = work_done_log[i]
                work_units = float(entry.get("work_units", "0"))
                timestamp = entry.get("timestamp", 0)
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
            task = entry.get("task", "Unknown")
            work_units = entry.get("work_units", "0")
            timestamp = entry.get("timestamp", 0)
            date_str = TimePoint.from_int(timestamp).__str__()
            time_amount = TimeAmount(f"{work_units}p")
            self.__botPrint(f"{date_str}: {time_amount} on {task}")
        
        self.__botPrint("\n/list - return back to the task list")
        
    def __renderTaskAgenda(self, message: IMessage):
        self.__botPrint("(Info) Task Agenda Render Mode")
        
        # Get content from message
        date = message.content.get('date', "Today")
        active_urgent_tasks = message.content.get('active_urgent_tasks', [])
        planned_urgent_tasks = message.content.get('planned_urgent_tasks', [])
        planned_tasks_by_date = message.content.get('planned_tasks_by_date', {})
        other_tasks = message.content.get('other_tasks', [])
        
        # Display the agenda header
        self.__botPrint(f"Agenda for {date}:\n")
        
        # Display active urgent tasks
        if active_urgent_tasks:
            self.__botPrint("# Active Urgent tasks:")
            for task in active_urgent_tasks:
                self.__botPrint(f"- {task['description']} (Context: {task['context']})")
            self.__botPrint("")
        
        # Display planned urgent tasks
        if planned_urgent_tasks:
            self.__botPrint("# Planned Urgent tasks:")
            for date, tasks in planned_tasks_by_date.items():
                self.__botPrint(f"## {date}")
                for task in tasks:
                    self.__botPrint(f"\t- {task['description']} (Context: {task['context']})")
            self.__botPrint("")
        
        # Display other tasks
        if other_tasks:
            self.__botPrint("# Other tasks:")
            for task in other_tasks:
                self.__botPrint(f"- {task['description']} (Context: {task['context']})")
            self.__botPrint("")
        
        self.__botPrint("/list - return back to the task list")
        
    def __renderTaskInformation(self, message: IMessage):
        self.__botPrint("(Info) Task Information Render Mode")
        
        # Extract task information from the message
        task_description = message.content.get('description', 'No description')
        task_context = message.content.get('context', 'No context')
        task_start_date = message.content.get('start_date', 'No start date')
        task_due_date = message.content.get('due_date', 'No due date')
        task_total_cost = message.content.get('total_cost', 0)
        task_remaining_cost = message.content.get('remaining_cost', 0)
        task_severity = message.content.get('severity', 0)
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
        if 'heuristics' in message.content:
            self.__botPrint("\nHeuristic Values:")
            for heuristic in message.content.get('heuristics', []):
                self.__botPrint(f"- {heuristic['name']}: {heuristic['comment']}")
        
        if 'metadata' in message.content:
            self.__botPrint("\nMetadata:")
            self.__botPrint(message.content['metadata'])
        
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

        render_mode = message.content.get('render_mode', RenderMode.RAW_TEXT)
        self.__renders[render_mode](message)
        pass
