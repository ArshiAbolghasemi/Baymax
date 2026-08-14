"""Shared transport, normalization, caching, and error behavior for tools."""

import copy
import html
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_exponential

from common.logging import get_logger
from config import get_config

logger = get_logger(__name__)


class ExternalServiceError(RuntimeError):
    """A retrieval failure, distinct from a valid response with no matches."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _TransientStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"transient HTTP status {status_code}")
        self.status_code = status_code


def _is_retryable_http_error(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (httpx.TimeoutException, httpx.NetworkError, _TransientStatusError),
    )


def _log_http_retry(tool_name: str, state: RetryCallState) -> None:
    exception = state.outcome.exception() if state.outcome else None
    status = getattr(exception, "status_code", "-")
    delay = state.next_action.sleep if state.next_action else 0
    logger.warning(
        "external http retry tool=%s attempt=%d status=%s error_type=%s next_wait_seconds=%.2f",
        tool_name,
        state.attempt_number,
        status,
        type(exception).__name__ if exception else "unknown",
        delay,
    )


_CacheValue = tuple[float, dict[str, Any]]
_cache: dict[tuple[object, ...], _CacheValue] = {}


async def cached(
    key: tuple[object, ...],
    ttl_seconds: float,
    producer: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    now = time.monotonic()
    cached_value = _cache.get(key)
    if cached_value and cached_value[0] > now:
        logger.debug("external tool cache hit tool=%s", key[0])
        return copy.deepcopy(cached_value[1])

    logger.debug("external tool cache miss tool=%s", key[0])
    started = time.perf_counter()
    value = await producer()
    if value.get("status") != "error":
        max_entries = get_config().medical_tools.max_cache_entries
        if len(_cache) >= max_entries:
            expired = [cache_key for cache_key, item in _cache.items() if item[0] <= now]
            for cache_key in expired:
                _cache.pop(cache_key, None)
            while len(_cache) >= max_entries:
                _cache.pop(next(iter(_cache)))
        _cache[key] = (now + ttl_seconds, copy.deepcopy(value))
    elapsed = (time.perf_counter() - started) * 1_000
    logger.info(
        "external tool completed tool=%s status=%s cached=%s elapsed_ms=%.1f",
        key[0],
        value.get("status", "unknown"),
        value.get("status") != "error",
        elapsed,
    )
    return value


def clear_tool_cache() -> None:
    """Clear the process-local external reference cache."""
    _cache.clear()


async def get(
    tool_name: str, url: str, *, params: dict[str, object] | None = None
) -> httpx.Response:
    """GET with configured timeouts and bounded transient-only retries."""
    config = get_config().medical_tools
    timeout = httpx.Timeout(
        connect=config.http_connect_timeout,
        read=config.http_read_timeout,
        write=config.http_write_timeout,
        pool=config.http_pool_timeout,
    )
    started = time.perf_counter()
    last_error: Exception | None = None
    last_status: int | None = None
    retrying = AsyncRetrying(
        retry=retry_if_exception(_is_retryable_http_error),
        stop=stop_after_attempt(config.http_max_retries + 1),
        wait=wait_exponential(
            multiplier=config.http_retry_multiplier,
            min=config.http_retry_min_wait,
            max=config.http_retry_max_wait,
        ),
        before_sleep=partial(_log_http_retry, tool_name),
        reraise=True,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async for attempt in retrying:
                with attempt:
                    attempt_number = attempt.retry_state.attempt_number
                    logger.debug(
                        "external http request tool=%s attempt=%d host=%s",
                        tool_name,
                        attempt_number,
                        httpx.URL(url).host,
                    )
                    response = await client.get(url, params=params)
                    last_status = response.status_code
                    if response.status_code in config.transient_status_codes:
                        raise _TransientStatusError(response.status_code)
                    response.raise_for_status()
                    elapsed = (time.perf_counter() - started) * 1_000
                    logger.info(
                        "external tool=%s latency_ms=%.1f status=%s attempts=%d error_type=-",
                        tool_name,
                        elapsed,
                        response.status_code,
                        attempt_number,
                    )
                    return response
    except (
        _TransientStatusError,
        httpx.HTTPStatusError,
        httpx.NetworkError,
        httpx.TimeoutException,
    ) as exc:
        last_error = exc

    elapsed = (time.perf_counter() - started) * 1_000
    error_type = type(last_error).__name__ if last_error else "ExternalServiceError"
    logger.warning(
        "external tool=%s latency_ms=%.1f status=%s error_type=%s",
        tool_name,
        elapsed,
        last_status if last_status is not None else "-",
        error_type,
    )
    raise ExternalServiceError(
        "The authoritative source could not be retrieved.", status_code=last_status
    ) from last_error


def clean_text(value: str | None, *, limit: int) -> str:
    if not value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value))
    compact = re.sub(r"\s+", " ", without_tags).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def element_text(element: ET.Element | None, *, limit: int) -> str:
    return clean_text(" ".join(element.itertext()) if element is not None else "", limit=limit)


def error_payload(
    identity: dict[str, Any], source: str, source_url: str, exc: Exception
) -> dict[str, Any]:
    status_code = exc.status_code if isinstance(exc, ExternalServiceError) else None
    error: dict[str, Any] = {
        "type": "retrieval_error",
        "message": "The authoritative source is temporarily unavailable or returned invalid data.",
    }
    if status_code is not None:
        error["http_status"] = status_code
    return {
        **identity,
        "status": "error",
        "source": source,
        "url": source_url,
        "error": error,
    }
