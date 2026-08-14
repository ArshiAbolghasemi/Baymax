"""Shared transport, normalization, caching, and error behavior for tools."""

import asyncio
import copy
import html
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from baymax.common.logging import get_logger
from baymax.config import get_config

logger = get_logger(__name__)


class ExternalServiceError(RuntimeError):
    """A retrieval failure, distinct from a valid response with no matches."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                logger.debug(
                    "external http request tool=%s attempt=%d host=%s",
                    tool_name,
                    attempt + 1,
                    httpx.URL(url).host,
                )
                response = await client.get(url, params=params)
                last_status = response.status_code
                if response.status_code in config.transient_status_codes and attempt < 2:
                    logger.warning(
                        "external http retry tool=%s attempt=%d status=%d",
                        tool_name,
                        attempt + 1,
                        response.status_code,
                    )
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                response.raise_for_status()
                elapsed = (time.perf_counter() - started) * 1_000
                logger.info(
                    "external tool=%s latency_ms=%.1f status=%s error_type=-",
                    tool_name,
                    elapsed,
                    response.status_code,
                )
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < 2:
                    logger.warning(
                        "external http retry tool=%s attempt=%d error_type=%s",
                        tool_name,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                break

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
