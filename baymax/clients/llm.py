"""Streaming chat client for an OpenAI-compatible endpoint (vLLM).

Sits beside the embedding and Qdrant clients: connection-level infrastructure,
with no knowledge of what the conversation is about. What to say — the system
prompt, how much history to replay — belongs to the domain using it.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from openai import AsyncOpenAI

from baymax.common.logging import get_logger
from baymax.config import get_config

logger = get_logger(__name__)


class ChatLLM:
    """Wraps ``chat.completions`` with ``stream=True``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        logger.info("chat llm ready model=%s base_url=%s", model, base_url)

    @property
    def model(self) -> str:
        return self._model

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield reply text chunk by chunk as the model produces it."""
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if not chunk.choices:
                continue  # usage-only chunk, sent last by some servers
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


@lru_cache(maxsize=1)
def get_llm() -> ChatLLM:
    config = get_config().llm
    return ChatLLM(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
