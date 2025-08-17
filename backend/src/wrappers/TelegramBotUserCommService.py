import telegram

from src.wrappers.Messaging import IAgent, IMessage, RenderMode, UserAgent, InboundMessage
from src.wrappers.interfaces.IUserCommService import IUserCommService
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry


class TelegramBotUserCommService(IUserCommService):
    def __init__(self, bot: telegram.Bot, fileBroker: IFileBroker, agent: IAgent):
        self.bot: telegram.Bot = bot
        self.fileBroker: IFileBroker = fileBroker
        self.offset = None
        self.agent: IAgent = agent

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

    async def __renderFilterList(self, message: IMessage):
        filter_list = message.content.get('filterList', [])
        chat_id = message.destination.id
        if not filter_list:
            await self.bot.send_message(chat_id, "No filters available", parse_mode=None)
            return
        text = "Available Filters:\n"
        for i, filter_info in enumerate(filter_list):
            name = filter_info.get('name', f'Filter {i+1}')
            description = filter_info.get('description', '')
            enabled = filter_info.get('enabled', False)
            text += f" - (/filter_{i+1}) {name}: {description} [{'ENABLED' if enabled else 'DISABLED'}]\n"
        await self.bot.send_message(chat_id, text, parse_mode=None)
        pass

    async def initialize(self) -> None:
        await self.bot.initialize()
        pass

    async def shutdown(self) -> None:
        await self.bot.shutdown()
        pass

    def __preprocessMessageText(self, text: str) -> str:
        if not text.startswith("/"):
            text = "/" + text

        parts = text.split(' ')

        if parts and "__" in parts[0]:
            parts[0] = parts[0].replace("__", " ")

        text = ' '.join(parts)
        return text

    async def __getMessageUpdates_legacy(self) -> tuple[int, str]:
        result = await self.bot.getUpdates(limit=1, timeout=1, allowed_updates=['message'], offset=self.offset)
        if len(result) == 0:
            return None
        elif result[0].message.text is not None:
            self.offset = result[0].update_id + 1
            return (result[0].message.chat.id, self.__preprocessMessageText(result[0].message.text))
        elif result[0].message.document is not None:
            self.offset = result[0].update_id + 1
            file_id = result[0].message.document.file_id
            file = await self.bot.get_file(file_id)
            fileContent = await file.download_as_bytearray()
            self.fileBroker.writeFileContent(FileRegistry.LAST_RECEIVED_FILE, fileContent.decode())
            detectedFileType = "json"
            return (result[0].message.chat.id, f"/import {detectedFileType}")
        else:
            self.offset = result[0].update_id + 1
            return None

    async def getMessageUpdates(self) -> list[IMessage]:
        """
        Gets messages from the Telegram Bot API.
        Splits the message by lines and creates an InboundMessage for each line.

        Returns:
            A list of InboundMessage objects, one per line in the original message.
            Returns an empty list if no updates.
        """
        # Get the raw message using the legacy method
        result = await self.__getMessageUpdates_legacy()

        if result is None:
            return []

        chat_id, message_text = result

        # Create source and destination agents
        source_agent = UserAgent(str(chat_id))
        destination_agent = self.getBotAgent()

        # Split the message by lines and create an InboundMessage for each non-empty line
        messages = []
        for line in message_text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            # Extract command and arguments for this line
            parts = line.split()
            command = parts[0].strip('/')  # Remove the leading '/'
            args = parts[1:] if len(parts) > 1 else []

            # Create and add the inbound message
            messages.append(InboundMessage(source_agent, destination_agent, command, args))

        # If no valid messages were created, return an empty list
        return messages

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        import io
        f = io.BufferedReader(io.BytesIO(data))

        await self.bot.send_document(chat_id, f, filename="export.txt")

    async def sendMessage(self, message: IMessage) -> None:
        if message.type != "OutboundMessage":
            raise ValueError("Only OutboundMessage is supported in TelegramBotUserCommService")

        render_mode = message.content.get('render_mode', RenderMode.RAW_TEXT)
        await self.__renders[render_mode](message)

    async def __renderTaskList(self, message: IMessage):
        algorithm_name = message.content.get('algorithm_name', 'Unknown Algorithm')
        algorithm_desc = message.content.get('algorithm_desc', 'No description provided')
        sort_heuristic = message.content.get('sort_heuristic', 'No heuristic provided')
        interactive = message.content.get('interactive', True)
        current_page = message.content.get('current_page', 1)
        total_pages = message.content.get('total_pages', 1)
        active_filters = message.content.get('active_filters', [])
        tasks = message.content.get('tasks', [])  # id, description, context

        interactiveId = "/task_" if interactive else ""
        subTaskListDescriptions = [(f"{interactiveId}{i+1}: {description}") for i, description in enumerate(tasks)]

        taskListString = f"Task List\n\nAlgorithm: {algorithm_name}\nDescription: {algorithm_desc}\nSort Heuristic: {sort_heuristic}\nActive Filters: {', '.join(active_filters) if active_filters else 'None'}\nTasks:\n"
        for desc in subTaskListDescriptions:
            taskListString += f"  - {desc}\n"

        if interactive:
            taskListString += f"\nPage {current_page} of {total_pages}\n"
            taskListString += "/next - Next page\n/previous - Previous page\n"
            taskListString += "/search [search terms] - Search for tasks\n"
            taskListString += "/agenda - Show today's agenda\n/filter - configure filters\n"
            taskListString += "/heuristic - Show available heuristics\n"
            taskListString += "/algorithm - Show available algorithms\n"

        chat_id = message.destination.id
        text = taskListString

        await self.bot.send_message(chat_id, text, parse_mode=None)

    async def __renderRawText(self, message: IMessage):
        chat_id = message.destination.id
        text = message.content.get('text', 'No message')
        await self.bot.send_message(chat_id, text, parse_mode=None)

    async def __notifyListUpdated(self, message: IMessage):
        algorithm_desc = message.content.get('algorithm_desc', 'No description provided')
        most_priority_task = message.content.get('task', {"id": 0, "description": "empty task list", "context": "no context"})

        chat_id = message.destination.id

        text = f"List updated with algorithm: {algorithm_desc}\nMost prioritary task: {most_priority_task['description']} (ID: /task_{most_priority_task['id']}, Context: {most_priority_task['context']})"
        await self.bot.send_message(chat_id, text, parse_mode=None)

    async def __renderHeuristicList(self, message: IMessage):
        heuristic_list = message.content.get('heuristicList', [])

        if not heuristic_list:
            chat_id = message.destination.id
            await self.bot.send_message(chat_id, "No heuristics available", parse_mode=None)
            return

        chat_id = message.destination.id
        text = "Available Heuristics:\n"
        for i, heuristic in enumerate(heuristic_list):
            text += f" - (/heuristic_{i+1}) {heuristic['name']}: {heuristic['description']}\n"

        await self.bot.send_message(chat_id, text, parse_mode=None)

    async def __renderAlgorithmList(self, message: IMessage):
        algorithm_list = message.content.get('algorithmList', [])

        if not algorithm_list:
            chat_id = message.destination.id
            await self.bot.send_message(chat_id, "No algorithms available", parse_mode=None)
            return

        chat_id = message.destination.id
        text = "Available Algorithms:\n"
        for i, algorithm in enumerate(algorithm_list):
            text += f" - (/algorithm_{i+1}) {algorithm['name']}: {algorithm['description']}\n"

        await self.bot.send_message(chat_id, text, parse_mode=None)

    async def __renderTaskStats(self, message: IMessage):
        # Import time management classes
        from backend.src.wrappers.TimeManagement import TimePoint, TimeAmount
        
        # Get chat_id from message
        chat_id = message.destination.id
        
        # Extract data from the message
        workload = message.content.get('workload', "0p")
        remaining_effort = message.content.get('remaining_effort', "0p")
        heuristic_value = message.content.get('heuristic_value', "0")
        heuristic_name = message.content.get('heuristic_name', "Unknown")
        offender = message.content.get('offender', "None")
        offender_max = message.content.get('offender_max', "0p")
        work_done_log = message.content.get('work_done_log', [])
        
        # Format the message with Markdown for Telegram
        stats_message = "Work done in the last 7 days:\n"
        stats_message += "`|    Date    | Work  Done |`\n"
        stats_message += "`|------------|------------|`\n"
        
        # For Telegram display, we'll calculate this from the last 7 days of logs if available
        total_work = 0
        for i in range(min(7, len(work_done_log))):
            if i < len(work_done_log):
                entry = work_done_log[i]
                work_units = float(entry.get("work_units", "0"))
                timestamp = entry.get("timestamp", 0)
                date_str = TimePoint.from_int(timestamp).to_string()
                stats_message += f"`| {date_str} |    {work_units}    |`\n"
                total_work += work_units
        
        # Add average work done per day
        average_work = round(total_work / 7, 2) if work_done_log else 0
        stats_message += "`|------------|------------|`\n"
        stats_message += f"`|   Average  |    {average_work}    |`\n"
        stats_message += "`|------------|------------|`\n\n"
        
        # Display workload statistics
        stats_message += "Workload statistics:\n"
        stats_message += f"`current workload: {workload} per day`\n"
        stats_message += f"    `max Offender: '{offender}' with {offender_max} per day`\n"
        stats_message += f"`total remaining effort: {remaining_effort}`\n"
        stats_message += f"`max {heuristic_name}: {heuristic_value}`\n\n"
        
        # Display work done log
        stats_message += "Work done log:\n"
        for entry in work_done_log:
            task = entry.get("task", "Unknown")
            work_units = entry.get("work_units", "0")
            timestamp = entry.get("timestamp", 0)
            date_str = TimePoint.from_int(timestamp).to_string()
            time_amount = TimeAmount(f"{work_units}p")
            stats_message += f"`{date_str}: {time_amount} on {task}`\n"
        
        stats_message += "\n/list - return back to the task list"
        
        # Send the message with Markdown formatting
        await self.bot.send_message(chat_id, stats_message, parse_mode="Markdown")
        
    async def __renderTaskAgenda(self, message: IMessage):
        # Get chat_id from message
        chat_id = message.destination.id
        
        # Extract data from the message
        date = message.content.get('date', "Unknown Date")
        active_urgent_tasks = message.content.get('active_urgent_tasks', [])
        planned_tasks_by_date = message.content.get('planned_tasks_by_date', {})
        other_tasks = message.content.get('other_tasks', [])
        
        # Format the message with Markdown for Telegram
        agenda_message = f"*Agenda for {date}*\n\n"
        
        # Display active urgent tasks
        if active_urgent_tasks:
            agenda_message += "*Active Urgent tasks:*\n"
            for task in active_urgent_tasks:
                agenda_message += f"- {task['description']} (Context: {task['context']})\n"
            agenda_message += "\n"
        
        # Display planned urgent tasks by date
        if planned_tasks_by_date:
            agenda_message += "*Planned tasks:*\n"
            for date, tasks in planned_tasks_by_date.items():
                agenda_message += f"*{date}*\n"
                for task in tasks:
                    agenda_message += f"- {task['description']} (Context: {task['context']})\n"
            agenda_message += "\n"
        
        # Display other tasks
        if other_tasks:
            agenda_message += "*Other tasks:*\n"
            for task in other_tasks:
                agenda_message += f"- {task['description']} (Context: {task['context']})\n"
            agenda_message += "\n"
        
        agenda_message += "/list - return back to the task list"
        
        # Send the message with Markdown formatting
        await self.bot.send_message(chat_id, agenda_message, parse_mode="Markdown")
        
    async def __renderTaskInformation(self, message: IMessage):
        # Get chat_id from message
        chat_id = message.destination.id
        
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
        task_info = f"*Task:* {task_description}\n"
        task_info += f"*Context:* {task_context}\n"
        task_info += f"*Start Date:* {task_start_date}\n"
        task_info += f"*Due Date:* {task_due_date}\n"
        task_info += f"*Total Cost:* {task_total_cost}\n"
        task_info += f"*Remaining:* {task_remaining_cost}\n"
        task_info += f"*Severity:* {task_severity}\n"
        
        # Include extended information if available
        if 'heuristics' in message.content:
            task_info += "\n*Heuristic Values:*\n"
            for heuristic in message.content.get('heuristics', []):
                task_info += f"- *{heuristic['name']}:* {heuristic['comment']}\n"
        
        if 'metadata' in message.content:
            task_info += f"\n*Metadata:*\n`{message.content['metadata']}`\n"
        
        # Add command options
        task_info += "\n/list - Return to list"
        task_info += "\n/done - Mark task as done"
        task_info += "\n/set [param] [value] - Set task parameter"
        task_info += "\n/work [work_units] - Invest work units in the task"
        task_info += "\n/snooze - Snooze the task for 5 minutes"
        task_info += "\n/info - Show extended information"
        
        # Send the message with Markdown formatting
        await self.bot.send_message(chat_id, task_info, parse_mode="Markdown")

    def getBotAgent(self):
        return self.agent
