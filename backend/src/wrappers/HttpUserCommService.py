"""HTTP listener that adapts requests to the resource API and channel interface."""

import asyncio
import threading
import uuid
from typing import Any, Dict, List, Optional

from aiohttp import web

from src.api.HttpApiV1 import HttpApiV1
from src.domain.TaskApplicationService import TaskApplicationService
from src.wrappers.Messaging import (
    IAgent,
    IMessage,
    OutboundMessage,
)
from src.wrappers.TimeManagement import TimePoint
from src.wrappers.interfaces.IUserCommService import IUserCommService


class HttpUserCommService(IUserCommService):
    """Run the HTTP v1 API while retaining the internal message-channel shape."""

    def __init__(
        self,
        url: str,
        port: int,
        token: str,
        chat_id: int,
        agent: IAgent,
        ssl_cert_path: Optional[str] = None,
        ssl_key_path: Optional[str] = None,
        application_service: TaskApplicationService | None = None,
        api_prefix: str = "/api/v1",
    ) -> None:
        self.url = url
        self.port = port
        self.token = token
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.chat_id = chat_id
        self.agent = agent
        self.application_service = application_service
        self.api_prefix = api_prefix
        self.api = (
            HttpApiV1(application_service, token, api_prefix)
            if application_service is not None
            else None
        )
        self.pendingMessages: list[tuple[IMessage, asyncio.Future[IMessage]]] = []
        self.notificationQueue: list[tuple[IMessage, TimePoint]] = []
        self.lock = threading.Lock()
        self.req_id_counter = 0

    async def initialize(self) -> None:
        if self.api is None:
            raise ValueError("The HTTP API requires an application service")
        self.server = web.Server(self.__handle_request__)
        self.runner = web.ServerRunner(self.server)
        await self.runner.setup()

        # Keep the existing optional listener TLS configuration unchanged.
        ssl_context = None
        if self.ssl_cert_path and self.ssl_key_path:
            import ssl

            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self.ssl_cert_path, self.ssl_key_path)

        self.site = web.TCPSite(self.runner, self.url, self.port, ssl_context=ssl_context)
        await self.site.start()
        protocol = "HTTPS" if ssl_context else "HTTP"
        print(f"{protocol} User Communication Service started at {self.url}:{self.port}")

    async def shutdown(self) -> None:
        site = getattr(self, "site", None)
        runner = getattr(self, "runner", None)
        server = getattr(self, "server", None)
        if site is not None:
            await site.stop()
        if runner is not None:
            await runner.shutdown()
        if server is not None:
            await server.shutdown()

    async def getMessageUpdates(self) -> list[IMessage]:
        await asyncio.sleep(0)
        retval: list[IMessage] = []
        with self.lock:
            for message, future in self.pendingMessages:
                if not future.done():
                    retval.append(message)
        return [retval[0]] if retval else []

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        # HTTP file transfer is not part of the current API contract.
        return None

    async def getNotifications(self, delete_queue: bool = True) -> List[Dict[str, Any]]:
        """Retain the internal notification queue for later API integration."""
        with self.lock:
            notifications = [
                {"message": str(message.content.text), "timestamp": str(timestamp)}
                for message, timestamp in self.notificationQueue.copy()
            ]
            if delete_queue:
                self.notificationQueue.clear()
        return notifications

    async def sendMessage(self, message: IMessage) -> None:
        if not isinstance(message, OutboundMessage):
            raise ValueError("Only OutboundMessage is supported in HttpUserCommService")
        if message.content.requestId is None:
            with self.lock:
                self.notificationQueue.append((message, TimePoint.now()))
            return
        for pending_message, future in self.pendingMessages:
            if pending_message.content.requestId == message.content.requestId and not future.done():
                future.set_result(message)

    def getBotAgent(self) -> IAgent:
        return self.agent

    def __get_id_counter__(self) -> int:
        with self.lock:
            self.req_id_counter += 1
            return self.req_id_counter

    async def __handle_request__(self, request: web.BaseRequest) -> web.Response:
        # This guard supports old direct construction in embedded callers; API
        # mode in the application container always injects its service.
        if self.api is None:
            from src.api.ProblemDetails import problem_response

            request_id = str(uuid.uuid4())
            response = problem_response(
                status=503,
                code="service-unavailable",
                detail="The HTTP API is not configured",
                request_id=request_id,
                instance="/api/v1",
                token=self.token,
                effects_state="none",
            )
            return response

        if self.ssl_cert_path and self.ssl_key_path and not request.secure:
            from src.api.ProblemDetails import problem_response

            request_id = str(uuid.uuid4())
            return problem_response(
                status=403,
                code="https-required",
                detail="HTTPS is required for this listener",
                request_id=request_id,
                instance=self.api.prefix,
                token=self.token,
            )
        return await self.api.handle_request(request)
