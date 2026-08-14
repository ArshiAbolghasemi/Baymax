"""LangChain chat models, built from the shared LLM config.

LangChain is confined to this package: the rest of the codebase talks to vLLM
through :mod:`baymax.clients`, and only the workflow needs a model object that
LangGraph can stream from.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

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
        timeout=config.timeout,
        streaming=True,
        tags=[ANSWER_TAG],
    )


@lru_cache(maxsize=1)
def get_guardrail_model() -> ChatOpenAI:
    """Same endpoint, but pinned to a single deterministic token.

    ``temperature=0`` and a tiny ``max_tokens`` keep the classifier cheap and
    stop it from explaining itself.
    """
    config = get_config().llm
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        temperature=0.0,
        max_tokens=4,
        timeout=config.timeout,
        streaming=False,
        tags=[GUARDRAIL_TAG],
    )
