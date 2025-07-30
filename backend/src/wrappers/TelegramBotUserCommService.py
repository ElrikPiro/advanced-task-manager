import telegram

from backend.src.wrappers.Messaging import IAgent, IMessage, RenderMode
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
            RenderMode.ALGORITHM_LIST: self.__renderAlgorithmList
        }
        pass

    async def initialize(self) -> None:
        await self.bot.initialize()
        pass

    async def shutdown(self) -> None:
        await self.bot.shutdown()
        pass

    async def sendMessage_legacy(self, chat_id: int, text: str, parse_mode: str = None) -> None:
        await self.bot.send_message(chat_id, text, parse_mode=parse_mode)
        pass

    def __preprocessMessageText(self, text: str) -> str:
        if not text.startswith("/"):
            text = "/" + text

        parts = text.split(' ')

        if parts and "__" in parts[0]:
            parts[0] = parts[0].replace("__", " ")

        text = ' '.join(parts)
        return text

    async def getMessageUpdates_legacy(self) -> tuple[int, str]:
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

    async def sendFile_legacy(self, chat_id: int, data: bytearray) -> None:
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

    def getBotAgent(self):
        return self.agent
