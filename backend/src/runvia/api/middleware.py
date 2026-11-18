import logging
import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from runvia.core.request_context import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

# Client-supplied IDs end up in logs, so only a safe charset and length are
# reused; anything else (newlines, huge values) is replaced.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def is_valid_request_id(value: str) -> bool:
    return _VALID_REQUEST_ID.fullmatch(value) is not None


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and is_valid_request_id(incoming) else str(uuid.uuid4())

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)


class AccessLogMiddleware:
    """Emit one structured line per HTTP request, replacing uvicorn's access log.

    Logs the path without the query string: query parameters can carry tokens
    (e.g. OAuth callbacks), and spec §14 forbids logging them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = structlog.get_logger("runvia.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500
        start = time.perf_counter()

        async def send_capturing_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_capturing_status)
        finally:
            # On an unhandled exception the status stays 500; the traceback is
            # logged once by the server, so it is not repeated here.
            self.logger.log(
                logging.ERROR if status_code >= 500 else logging.INFO,
                "http_request",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
