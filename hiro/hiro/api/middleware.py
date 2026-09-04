"""HTTP middleware."""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hiro.common.logging import bind_correlation_id, get_logger
from hiro.common.tracing import get_tracer

logger = get_logger(__name__)

CORRELATION_HEADER = "X-Request-ID"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


class ChatTraceMiddleware:
    """Wrap a complete chat response, including SSE streaming, in one chain span."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != CHAT_COMPLETIONS_PATH:
            await self.app(scope, receive, send)
            return

        attributes: dict[str, str | int] = {
            "openinference.span.kind": "CHAIN",
            "http.request.method": scope["method"],
            "url.path": scope["path"],
        }
        headers = {key.lower(): value for key, value in scope["headers"]}
        if session_id := headers.get(b"x-session-uid"):
            attributes["session.id"] = session_id.decode(errors="replace")

        with get_tracer().start_as_current_span("chat.completions", attributes=attributes) as span:

            async def traced_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    span.set_attribute("http.response.status_code", message["status"])
                    response_headers = {
                        key.lower(): value for key, value in message.get("headers", [])
                    }
                    if session_id := response_headers.get(b"x-session-uid"):
                        span.set_attribute("session.id", session_id.decode(errors="replace"))
                await send(message)

            await self.app(scope, receive, traced_send)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id per request and log its outcome.

    Honours an inbound ``X-Request-ID`` so a caller's id flows through our logs
    and into the Celery task; echoes it back on the response either way.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        inbound = request.headers.get(CORRELATION_HEADER)

        with bind_correlation_id(inbound) as request_id:
            logger.info(
                "http request started method=%s path=%s client=%s",
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            started = time.perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                elapsed = (time.perf_counter() - started) * 1000
                logger.exception(
                    "http request failed method=%s path=%s elapsed_ms=%.1f",
                    request.method,
                    request.url.path,
                    elapsed,
                )
                raise

            elapsed = (time.perf_counter() - started) * 1000
            logger.info(
                "http request completed method=%s path=%s status=%d elapsed_ms=%.1f",
                request.method,
                request.url.path,
                response.status_code,
                elapsed,
            )
            response.headers[CORRELATION_HEADER] = request_id
            return response
