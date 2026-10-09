from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from translation_service.api.errors import error_response
from translation_service.core.errors import RequestBodyTooLargeError


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        error = RequestBodyTooLargeError(details={"max_request_body_bytes": self.max_bytes})
        try:
            declared_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared_length = 0
        if declared_length > self.max_bytes:
            await error_response(request, error)(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await error_response(request, error)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
