"""Streaming client for the OpenAI-compatible chat endpoint.

Only the assistant's text ever leaves this module. The wire carries whole
``chat.completion.chunk`` objects; everything except ``choices[0].delta.content``
is bookkeeping and is dropped here, so the UI never has to know the envelope.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from cli.config import Settings

DONE = "[DONE]"
DATA_PREFIX = "data:"


class ChatError(RuntimeError):
    """The endpoint could not be reached, or refused the request."""


def _delta_text(payload: dict[str, Any]) -> str:
    """Pull the assistant text out of one chunk, if it carries any.

    Chunks legitimately arrive with an empty delta — the opening role frame and
    the closing finish_reason frame both do — so "no text" is not an error.
    """
    choices = payload.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if isinstance(content, str) else ""


class ChatClient:
    """Talks to ``/v1/chat/completions`` and yields text as it arrives."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout, connect=10.0),
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[str]:
        try:
            response = await self._client.get(self._settings.models_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            msg = f"could not list models: {exc}"
            raise ChatError(msg) from exc
        return [entry["id"] for entry in response.json().get("data", [])]

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield the reply chunk by chunk.

        Raises :class:`ChatError` for transport failures, non-2xx responses, and
        the mid-stream error frame the server emits when generation fails after
        the response has already begun.
        """
        body = {
            "model": self._settings.model,
            "messages": messages,
            "stream": True,
            "session_uid": str(self._settings.session_uid),
        }
        if self._settings.user:
            body["user"] = self._settings.user

        try:
            async with self._client.stream(
                "POST", self._settings.completions_url, json=body
            ) as response:
                if response.status_code >= 400:
                    raise ChatError(await _error_text(response))

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith(DATA_PREFIX):
                        continue

                    data = line[len(DATA_PREFIX) :].strip()
                    if data == DONE:
                        return

                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue  # keep-alive or padding; nothing to show

                    if error := payload.get("error"):
                        msg = error.get("message", "the agent failed mid-response")
                        raise ChatError(msg)

                    if text := _delta_text(payload):
                        yield text
        except httpx.HTTPError as exc:
            msg = f"{type(exc).__name__}: {exc}"
            raise ChatError(msg) from exc


async def _error_text(response: httpx.Response) -> str:
    """Turn an error response into one readable line."""
    await response.aread()
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"

    detail = payload.get("detail") or payload.get("error")
    if isinstance(detail, dict):
        detail = detail.get("message")
    return f"HTTP {response.status_code}: {detail or response.text[:200]}"
