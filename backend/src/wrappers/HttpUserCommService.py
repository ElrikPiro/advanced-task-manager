import asyncio
from aiohttp import web

from backend.src.wrappers.Messaging import OutboundMessage
from src.wrappers.TelegramBotUserCommService import InboundMessage, UserAgent
from src.TelegramReportingService import IAgent, IMessage, IUserCommService


class HttpUserCommService(IUserCommService):

    def __init__(self, url: str, port: int, token: str, chat_id: int) -> None:
        self.url = url
        self.port = port
        self.token = token
        self.server = web.Server(self.__handle_request__)
        self.runner = web.ServerRunner(self.server)
        self.pendingMessages: list[tuple[IMessage, asyncio.Future[IMessage]]] = []
        self.chat_id = chat_id

    async def initialize(self) -> None:
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.url, self.port)
        await self.site.start()
        pass

    async def shutdown(self) -> None:
        await self.site.stop()
        await self.runner.shutdown()
        await self.server.shutdown()
        pass

    async def getMessageUpdates(self) -> list[IMessage]:
        pass

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        pass

    async def sendMessage(self, message: IMessage) -> None:
        pass

    def getBotAgent(self) -> IAgent:
        pass

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
        
        timeout = 5  # seconds
        while self.pendingMessages != []:
            await asyncio.sleep(0.1)
            timeout -= 0.1
            if timeout <= 0:
                return web.Response(status=408, text="Request Timeout: No pending messages")
        
        source_agent: IAgent = UserAgent(str(self.chat_id))
        destination_agent: IAgent = self.getBotAgent()
        message: InboundMessage = InboundMessage(source_agent, destination_agent, command, args)
        future: asyncio.Future[IMessage] = asyncio.get_event_loop().create_future()
        self.pendingMessages.append((message, future))

        await future
        outmessage = future.result()
        if not isinstance(outmessage, OutboundMessage):
            return web.Response(status=500, text="Internal Server Error: Invalid outbound message")

        content = outmessage.content
        
        # TODO: apply rendermode like in TelegramReportingService but just sending the json response
        


        return web.Response(text="OK")
