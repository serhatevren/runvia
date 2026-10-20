import re
import uuid

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
