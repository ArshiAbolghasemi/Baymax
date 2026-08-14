"""HTTP middleware."""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from common.logging import bind_correlation_id, get_logger

logger = get_logger(__name__)

CORRELATION_HEADER = "X-Request-ID"


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
