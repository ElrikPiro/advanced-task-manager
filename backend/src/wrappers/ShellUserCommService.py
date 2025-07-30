from backend.src.wrappers.Messaging import IAgent, IMessage, RenderMode
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
            RenderMode.ALGORITHM_LIST: self.__renderAlgorithmList
        }

    async def initialize(self) -> None:
        print("ShellUserBotService initialized")

    async def shutdown(self) -> None:
        print("ShellUserBotService shutdown")

    async def sendMessage_legacy(self, chat_id: int, text: str, parse_mode: str = None) -> None:
        print(f"[bot -> {chat_id}]: {text}")

    def __preprocessMessageText(self, text: str) -> str:
        if not text.startswith("/"):
            text = "/" + text

        return text

    async def getMessageUpdates_legacy(self) -> tuple[int, str]:
        text = input(f"[User({self.chatId})]: ")
        self.offset += 1
        return (self.chatId, self.__preprocessMessageText(text))

    async def sendFile_legacy(self, chat_id: int, data: bytearray) -> None:
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

    async def sendMessage(self, message: IMessage) -> None:
        if message.type != "OutboundMessage":
            raise ValueError("Only OutboundMessage is supported in ShellUserCommService")

        render_mode = message.content.get('render_mode', RenderMode.RAW_TEXT)
        self.__renders[render_mode](message)
        pass
