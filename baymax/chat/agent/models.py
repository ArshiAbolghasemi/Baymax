"""LangChain chat models, built from the shared LLM config.

LangChain is confined to this package: the rest of the codebase talks to vLLM
through :mod:`baymax.clients`, and only the workflow needs a model object that
LangGraph can stream from.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from baymax.chat.agent.tools import EXTERNAL_MEDICAL_TOOLS
from baymax.common.logging import get_logger
from baymax.config import get_config

logger = get_logger(__name__)

#: Tokens streamed out of the graph are filtered by node name, but tagging the
#: answer model as well makes traces readable.
ANSWER_TAG = "answer"
GUARDRAIL_TAG = "guardrail"


@lru_cache(maxsize=1)
def get_answer_model() -> ChatOpenAI:
    config = get_config().llm
    logger.info("answer model %s at %s", config.model, config.base_url)
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_retries=config.max_retries,
        timeout=config.timeout,
        streaming=True,
        tags=[ANSWER_TAG],
    )


@lru_cache(maxsize=1)
def get_tool_enabled_answer_model():
    """Answer model with external medical tools exposed for semantic selection."""
    logger.info(
        "binding answer model tools=%d strict=true choice=auto", len(EXTERNAL_MEDICAL_TOOLS)
    )
    return get_answer_model().bind_tools(
        EXTERNAL_MEDICAL_TOOLS,
        tool_choice="auto",
        strict=True,
    )


@lru_cache(maxsize=1)
def get_guardrail_model() -> ChatOpenAI:
    """Same endpoint, but pinned to a single deterministic token.

    ``temperature=0`` and a tiny ``max_tokens`` keep the classifier cheap and
    stop it from explaining itself.
    """
    config = get_config().llm
    logger.info("guardrail model %s at %s", config.model, config.base_url)
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=0.0,
        max_tokens=4,
        max_retries=config.max_retries,
        timeout=config.timeout,
        streaming=False,
        tags=[GUARDRAIL_TAG],
    )
