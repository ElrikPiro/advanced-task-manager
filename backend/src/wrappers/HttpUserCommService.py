import asyncio
import threading
import json
from aiohttp import web
from dataclasses import asdict

from src.wrappers.Messaging import OutboundMessage, RenderMode, TaskListContent
from src.wrappers.TelegramBotUserCommService import InboundMessage, UserAgent
from src.TelegramReportingService import IAgent, IMessage, IUserCommService
from src.Interfaces.ITaskModel import ITaskModel

# TODO: next steps:
# - integrate with the rest of the system (add to TelegramReportingServiceContainer as a new APP_MODE option)


class HttpUserCommService(IUserCommService):

    def __init__(self, url: str, port: int, token: str, chat_id: int, agent: IAgent) -> None:
        self.url = url
        self.port = port
        self.token = token
        self.server = web.Server(self.__handle_request__)
        self.runner = web.ServerRunner(self.server)
        self.pendingMessages: list[tuple[IMessage, asyncio.Future[IMessage]]] = []
        self.notificationQueue: list[IMessage] = []
        self.chat_id = chat_id
        self.lock = threading.Lock()
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
            RenderMode.TASK_INFORMATION: self.__renderTaskInformation,
            RenderMode.EVENTS: self.__renderEvents
        }

    async def initialize(self) -> None:
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.url, self.port)
        await self.site.start()
        self.req_id_counter: int = 0
        pass

    async def shutdown(self) -> None:
        await self.site.stop()
        await self.runner.shutdown()
        await self.server.shutdown()
        pass

    async def getMessageUpdates(self) -> list[IMessage]:
        retval = [self.pendingMessages.pop(0)[0]] if len(self.pendingMessages) > 0 else []
        return retval

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        # TODO: will need an arch refactor to send files over HTTP using messages
        pass

    async def getNotifications(self) -> list[IMessage]:
        """
        Retrieves all pending notifications from the notification queue.
        
        Returns:
            list[IMessage]: A list of all notification messages.
        """
        with self.lock:
            notifications = self.notificationQueue.copy()
            self.notificationQueue.clear()
        return notifications

    async def sendMessage(self, message: IMessage) -> None:
        if not isinstance(message, OutboundMessage):
            raise ValueError("Only OutboundMessage is supported in HttpUserCommService")
        if message.content.requestId is None:
            # Store notification in the notification queue
            with self.lock:
                self.notificationQueue.append(message)
        else:
            for pendingMessage, future in self.pendingMessages:
                if pendingMessage.content.requestId == message.content.requestId:
                    future.set_result(message)
        return

    def getBotAgent(self) -> IAgent:
        return self.agent

    def __get_id_counter__(self) -> int:
        retval: int = 0
        with self.lock:
            self.req_id_counter += 1
            retval = self.req_id_counter
        return retval

    async def __renderTaskList(self, message: IMessage) -> web.Response:
        taskListContent = message.content.taskListContent
        assert isinstance(taskListContent, TaskListContent)

        # get taskListContent and convert to json, taskListContent is a dataclass
        task_list_dict = asdict(taskListContent)
        json_response = json.dumps(task_list_dict, indent=2)
        return web.Response(text=json_response, content_type='application/json')
    
    async def __renderRawText(self, message: IMessage) -> web.Response:
        text = message.content.text or ""
        return web.Response(text=text, content_type='text/plain')
    
    async def __notifyListUpdated(self, message: IMessage) -> web.Response:
        algorithm_desc = message.content.text or ""
        most_priority_task = message.content.task
        assert isinstance(most_priority_task, ITaskModel)
        response_json = {
            "algorithm_description": algorithm_desc,
            "most_priority_task": most_priority_task.getDescription()
        }
        return web.Response(text=json.dumps(response_json, indent=2), content_type='application/json')
    
    async def __renderHeuristicList(self, message: IMessage) -> web.Response:
        heuristic_list = message.content.anonObjectList

        if not heuristic_list:
            return web.Response(status=200, text="{'error': 'No heuristics available'}", content_type='application/json')

        return web.Response(text=json.dumps(heuristic_list, indent=2), content_type='application/json')

    async def __renderAlgorithmList(self, message: IMessage) -> web.Response:
        algorithm_list = message.content.anonObjectList

        if not algorithm_list:
            return web.Response(status=200, text="{'error': 'No algorithms available'}", content_type='application/json')

        return web.Response(text=json.dumps(algorithm_list, indent=2), content_type='application/json')
    
    async def __renderFilterList(self, message: IMessage) -> web.Response:
        filter_list = message.content.filterListDict

        if not filter_list:
            return web.Response(status=200, text="{'error': 'No filters available'}", content_type='application/json')

        return web.Response(text=json.dumps(filter_list, indent=2), content_type='application/json')
    
    async def __renderTaskStats(self, message: IMessage) -> web.Response:
        workload_stats = message.content.workloadStats

        if not workload_stats:
            return web.Response(status=200, text="{'error': 'No workload stats available'}", content_type='application/json')

        return web.Response(text=json.dumps(asdict(workload_stats), indent=2), content_type='application/json')

    async def __renderTaskAgenda(self, message: IMessage) -> web.Response:
        agenda_content = message.content.agendaContent

        if not agenda_content:
            return web.Response(status=200, text="{'error': 'No agenda content available'}", content_type='application/json')

        return web.Response(text=json.dumps(asdict(agenda_content), indent=2), content_type='application/json')
    
    async def __renderTaskInformation(self, message: IMessage) -> web.Response:
        task_information = message.content.taskInformation

        if not task_information:
            return web.Response(status=200, text="{'error': 'No task information available'}", content_type='application/json')

        return web.Response(text=json.dumps(asdict(task_information), indent=2), content_type='application/json')
    
    async def __renderEvents(self, message: IMessage) -> web.Response:
        events_content = message.content.eventsContent

        if not events_content:
            return web.Response(status=200, text="{'error': 'No events content available'}", content_type='application/json')

        return web.Response(text=json.dumps(asdict(events_content), indent=2), content_type='application/json')

    async def __handle_request__(self, request: web.BaseRequest) -> web.Response:
        # check if request is https
        if request.secure is False:
            return web.Response(status=403, text="Forbidden: HTTPS required")
        
        # check if client token is valid
        client_token = request.headers.get('Authorization', '')
        if client_token != f"Bearer {self.token}":
            return web.Response(status=401, text="Unauthorized: Invalid token")

        command = request.rel_url.path.lstrip('/')
        args = request.rel_url.query.get('args', '').split(' ')
        
        source_agent: IAgent = UserAgent(str(self.chat_id))
        destination_agent: IAgent = self.getBotAgent()
        message: InboundMessage = InboundMessage(source_agent, destination_agent, command, args)
        message.content.requestId = self.__get_id_counter__()
        future: asyncio.Future[IMessage] = asyncio.get_event_loop().create_future()
        pendingMessage = (message, future)
        self.pendingMessages.append(pendingMessage)

        try:
            await asyncio.wait_for(future, timeout=5.0)
        except asyncio.TimeoutError:
            self.pendingMessages.remove(pendingMessage)
            return web.Response(status=408, text="Request Timeout: Response took too long")

        outmessage = future.result()
        if not isinstance(outmessage, OutboundMessage):
            return web.Response(status=500, text="Internal Server Error: Invalid outbound message")

        render_mode = message.content.renderMode or RenderMode.RAW_TEXT
        response: web.Response = await self.__renders[render_mode](message)
        return response
