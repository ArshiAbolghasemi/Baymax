"""LangChain chat models, built from the shared LLM config.

LangChain is confined to this package: the rest of the codebase talks to vLLM
through :mod:`clients`, and only the workflow needs a model object that
LangGraph can stream from.
"""

from functools import lru_cache
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI

from chat.agent.tools import EXTERNAL_MEDICAL_TOOLS
from common.logging import get_logger
from config import get_config

logger = get_logger(__name__)

#: Tokens streamed out of the graph are filtered by node name, but tagging the
#: answer model as well makes traces readable.
ANSWER_TAG = "answer"
GUARDRAIL_TAG = "guardrail"


@lru_cache(maxsize=1)
def get_answer_model() -> ChatOpenAI:
    config = get_config().chatbot
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
def get_answer_tool_schemas() -> list[dict[str, Any]]:
    """Convert tools without wrapping or mutating the configured chat model."""
    logger.info(
        "converting answer tools count=%d strict=true",
        len(EXTERNAL_MEDICAL_TOOLS),
    )
    return [convert_to_openai_tool(tool, strict=True) for tool in EXTERNAL_MEDICAL_TOOLS]


@lru_cache(maxsize=1)
def get_guardrail_model() -> ChatOpenAI:
    """Build the independently configured topic-classification model."""
    config = get_config().guardrail
    logger.info("guardrail model %s at %s", config.model, config.base_url)
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_retries=config.max_retries,
        timeout=config.timeout,
        streaming=False,
        tags=[GUARDRAIL_TAG],
    )
