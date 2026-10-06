"""HTTP listener that adapts requests to the resource API and channel interface."""

import asyncio
import logging
import ssl
import threading
import uuid
from typing import Any, Dict, Optional

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger
from aiohttp.web_request import BaseRequest
from aiohttp.web_response import StreamResponse
from aiohttp.web_protocol import RequestHandler

from src.api.HttpApiV1 import HttpApiV1
from src.domain.TaskApplicationService import TaskApplicationService
from src.NotificationHistoryStore import NotificationHistoryStore
from src.wrappers.Messaging import (
    IAgent,
    IMessage,
    OutboundMessage,
)
from src.wrappers.interfaces.IUserCommService import IUserCommService


class _SafeAiohttpServerLogger:
    """Keep aiohttp parser and handler diagnostics free of request data."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("aiohttp.server.http_api")

    def exception(self, *_args: object, **_kwargs: object) -> None:
        self._logger.error("HTTP request processing failed")

    def debug(self, *_args: object, **_kwargs: object) -> None:
        self._logger.debug("HTTP request diagnostic")

    def warning(self, *_args: object, **_kwargs: object) -> None:
        self._logger.warning("HTTP listener warning")


class _SafeAiohttpAccessLogger(AbstractAccessLogger):
    """Log response status and duration without request targets or headers."""

    def log(
        self,
        request: BaseRequest,
        response: StreamResponse,
        time: float,
    ) -> None:
        del request
        self.logger.info(
            "HTTP request completed status=%d elapsed=%.3f",
            response.status,
            time,
        )


class _SafeAiohttpRequestHandler(RequestHandler):
    """Replace aiohttp's attacker-controlled parse-error body with a constant."""

    def handle_error(
        self,
        request: BaseRequest,
        status: int = 500,
        exc: BaseException | None = None,
        message: str | None = None,
    ) -> StreamResponse:
        safe_message = None if status == 500 else "Invalid HTTP request"
        response = super().handle_error(request, status, exc, safe_message)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = uuid.uuid4().hex
        return response


class _SafeAiohttpServer(web.Server):
    """Create request handlers that sanitize parser failures before routing."""

    def __call__(self) -> RequestHandler:
        return _SafeAiohttpRequestHandler(
            self,
            loop=self._loop,
            **self._kwargs,
        )


class HttpUserCommService(IUserCommService):
    """Run the HTTP v1 API while retaining the internal message-channel shape."""

    def __init__(
        self,
        url: str,
        port: int,
        token: str,
        chat_id: int,
        agent: IAgent,
        tls_cert_chain_path: Optional[str] = None,
        tls_private_key_path: Optional[str] = None,
        application_service: TaskApplicationService | None = None,
        api_prefix: str = "/api/v1",
        notification_history_store: NotificationHistoryStore | None = None,
    ) -> None:
        self.url = url
        self.port = port
        self.token = token
        self.tls_cert_chain_path = tls_cert_chain_path
        self.tls_private_key_path = tls_private_key_path
        self.chat_id = chat_id
        self.agent = agent
        self.application_service = application_service
        self.api_prefix = api_prefix
        self.notification_history_store = notification_history_store
        self.api = (
            HttpApiV1(
                application_service,
                token,
                api_prefix,
                notification_history_store=notification_history_store,
            )
            if application_service is not None
            else None
        )
        self.pendingMessages: list[tuple[IMessage, asyncio.Future[IMessage]]] = []
        self.lock = threading.Lock()
        self.req_id_counter = 0

    async def initialize(self) -> None:
        if self.api is None:
            raise ValueError("The HTTP API requires an application service")
        ssl_context = self._create_ssl_context()
        history_store = self.notification_history_store
        if history_store is None:
            raise RuntimeError("Notification history is not configured")
        try:
            history_store.initialize()
        except Exception:
            raise RuntimeError("Notification history could not be initialized") from None
        server = _SafeAiohttpServer(
            self.__handle_request__,
            debug=False,
            logger=_SafeAiohttpServerLogger(),
            access_log=logging.getLogger("aiohttp.access.http_api"),
            access_log_class=_SafeAiohttpAccessLogger,
            access_log_format="",
        )
        runner = web.ServerRunner(server)
        try:
            await runner.setup()
            site = web.TCPSite(
                runner,
                self.url,
                self.port,
                ssl_context=ssl_context,
            )
            await site.start()
        except Exception:
            try:
                await runner.cleanup()
            except Exception:
                pass
            raise RuntimeError("HTTPS listener could not be started") from None

        self.server = server
        self.runner = runner
        self.site = site
        print("HTTPS User Communication Service started")

    def _create_ssl_context(self) -> ssl.SSLContext:
        cert_chain_path = self.tls_cert_chain_path
        private_key_path = self.tls_private_key_path
        if not isinstance(cert_chain_path, str) or not isinstance(private_key_path, str):
            raise RuntimeError(
                "TLS certificate chain and private key paths are required"
            )
        if not cert_chain_path.strip() or not private_key_path.strip():
            raise RuntimeError(
                "TLS certificate chain and private key paths are required"
            )

        try:
            context = self._new_tls_context()
            context.load_cert_chain(
                certfile=cert_chain_path,
                keyfile=private_key_path,
                # Supplying a callback prevents OpenSSL from prompting on
                # stdin for an encrypted key. Keys that need a passphrase
                # therefore fail closed during initialization.
                password=lambda: "",
            )
        except Exception as error:
            raise RuntimeError(
                "TLS certificate chain and private key could not be loaded"
            ) from error
        return context

    @staticmethod
    def _new_tls_context() -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

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

    async def getNotifications(self) -> Dict[str, Any]:
        """Return the full persisted notification history without consuming it."""
        history_store = self.notification_history_store
        if history_store is None:
            raise RuntimeError("Notification history is not configured")
        return history_store.read().to_dict()

    async def sendMessage(self, message: IMessage) -> None:
        if not isinstance(message, OutboundMessage):
            raise ValueError("Only OutboundMessage is supported in HttpUserCommService")
        if message.content.requestId is None:
            history_store = self.notification_history_store
            notification_text = message.content.text
            if history_store is None:
                raise RuntimeError("Notification history is not configured")
            if not isinstance(notification_text, str):
                raise ValueError("Notification text must be a string")
            history_store.append(notification_text)
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

        if not request.secure:
            from src.api.ProblemDetails import problem_response

            request_id = str(uuid.uuid4())
            return problem_response(
                status=403,
                code="https-required",
                detail="HTTPS is required for this listener",
                request_id=request_id,
                instance=self.api.prefix,
                token=self.token,
                effects_state="none",
            )
        return await self.api.handle_request(request)
