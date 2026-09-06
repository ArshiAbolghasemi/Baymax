"""Every prompt the assistant uses, fetched from Phoenix.

No prompt text lives in this repository. The wording, the persona, the refusal
and the empty-retrieval stand-ins are all versioned in Phoenix and edited
there; hiro reads them per turn, so an edit takes effect on the next question
without a deploy.

That also means Phoenix is a hard dependency of answering: if it is down or a
prompt is missing, the run fails rather than falling back to something
plausible — there is nothing to fall back to, by design.

Which prompt each step fetches is configuration — the ``CHAT_PROMPT_*``
settings on :class:`~hiro.chat.config.ChatConfig`. That name is the one thing
that cannot itself be fetched from Phoenix.
"""

from functools import lru_cache

from langchain_core.messages import BaseMessage, convert_to_messages
from phoenix.client import AsyncClient

from hiro.chat.tracing import trace
from hiro.common.logging import get_logger
from hiro.config import get_config

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_client() -> AsyncClient:
    config = get_config().phoenix
    logger.info("phoenix client base_url=%s", config.base_url)
    return AsyncClient(base_url=config.base_url, api_key=config.api_key or None)


@trace(
    lambda identifier, **_: f"prompt {identifier}",
    attributes=lambda identifier, **_: {"prompt.identifier": identifier},
    output=lambda messages: [f"{m.type}: {m.content}" for m in messages],
)
async def get_messages(identifier: str, **variables: str) -> list[BaseMessage]:
    """Fetch one prompt and render its variables.

    Phoenix does the substitution, so a template that gains or loses a variable
    needs no change here.
    """
    tag = get_config().chat.prompt_tag(identifier) or None
    version = await get_client().prompts.get(prompt_identifier=identifier, tag=tag)
    messages = convert_to_messages(list(version.format(variables=variables)["messages"]))
    logger.debug(
        "prompt fetched identifier=%s tag=%s messages=%d variables=%s",
        identifier,
        tag,
        len(messages),
        sorted(variables),
    )
    return messages


async def get_text(identifier: str) -> str:
    """Fetch a prompt that is used as a fixed string rather than as a conversation."""
    messages = await get_messages(identifier)
    return "\n".join(str(message.content) for message in messages)
