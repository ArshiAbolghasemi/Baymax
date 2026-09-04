"""OpenAI-compatible HTTP API for the database-backed Baymax agent."""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from hiro.chat import service
from hiro.chat.agent.events import AgentEvent, TextDelta, ToolCall
from hiro.chat.schemas import (
    AssistantMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionChoice,
    ModelInfo,
    ModelList,
)
from hiro.common.logging import get_logger
from hiro.config import get_config
from hiro.db.dependencies import AsyncSessionDep

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])


def _completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex}"


def _sse(payload: dict[str, Any] | str) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return f"data: {body}\n\n"


def _chunk(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _delta(event: AgentEvent) -> dict[str, Any]:
    """One agent event as an OpenAI chunk delta.

    Text and tool calls use the standard fields, so an OpenAI client reads the
    reply as it always did and a tool-aware one sees the calls. Tool *results*
    have no standard shape — OpenAI expects the client to run the tools — so
    they travel under ``tool_results``, which other clients ignore.
    """
    if isinstance(event, TextDelta):
        return {"content": event.text}
    if isinstance(event, ToolCall):
        return {
            "tool_calls": [
                {
                    "index": 0,
                    "id": event.id,
                    "type": "function",
                    "function": {
                        "name": event.name,
                        "arguments": json.dumps(event.arguments, separators=(",", ":")),
                    },
                }
            ]
        }
    return {
        "tool_results": [
            {
                "tool_call_id": event.tool_call_id,
                "name": event.name,
                "content": event.content,
            }
        ]
    }


async def _completion_events(
    turn: service.PreparedTurn,
    *,
    completion_id: str,
    created: int,
    model: str,
) -> AsyncIterator[str]:
    logger.info(
        "openai stream started completion_id=%s session_uid=%s model=%s",
        completion_id,
        turn.session_uid,
        model,
    )
    yield _sse(
        _chunk(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant", "content": ""},
        )
    )
    try:
        async for event in service.stream_reply(turn):
            yield _sse(
                _chunk(
                    completion_id=completion_id,
                    created=created,
                    model=model,
                    delta=_delta(event),
                )
            )
        yield _sse(
            _chunk(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={},
                finish_reason="stop",
            )
        )
        yield _sse("[DONE]")
        logger.info(
            "openai stream completed completion_id=%s session_uid=%s",
            completion_id,
            turn.session_uid,
        )
    except asyncio.CancelledError:
        logger.warning(
            "openai stream cancelled completion_id=%s session_uid=%s",
            completion_id,
            turn.session_uid,
        )
        raise
    except Exception:
        logger.exception(
            "openai stream failed completion_id=%s session_uid=%s",
            completion_id,
            turn.session_uid,
        )
        yield _sse(
            {
                "error": {
                    "message": "The agent could not complete the response.",
                    "type": "server_error",
                    "code": "agent_generation_failed",
                }
            }
        )
        yield _sse("[DONE]")


@router.get("/models", response_model=ModelList, summary="List available agent models")
async def list_models() -> ModelList:
    model = get_config().chat.agent_model_name
    logger.info("openai model list requested advertised_model=%s", model)
    return ModelList(data=[ModelInfo(id=model)])


@router.post(
    "/chat/completions",
    response_model=None,
    summary="Create an agent chat completion",
    description=(
        "OpenAI-compatible chat completions endpoint. Set stream=true for SSE. "
        "Conversation identity resolves from X-Session-UID, body session_uid, "
        "body chat_id, then a deterministic user/first-message fallback. "
        "Only the model advertised by GET /v1/models is served; any other is "
        "refused with 404. The agent supplies its own prompt, so system and "
        "assistant messages in the request are ignored."
    ),
)
async def create_chat_completion(
    payload: ChatCompletionRequest,
    session: AsyncSessionDep,
    x_session_uid: Annotated[uuid.UUID | None, Header(alias="X-Session-UID")] = None,
):
    started = time.perf_counter()
    completion_id = _completion_id()
    model = get_config().chat.agent_model_name
    logger.info(
        "openai completion requested completion_id=%s requested_model=%s stream=%s messages=%d",
        completion_id,
        payload.model,
        payload.stream,
        len(payload.messages),
    )

    # This endpoint serves one agent. Answering a request for some other model
    # would silently return Baymax's answer under that model's name, so refuse
    # it the way OpenAI does — a client picking a model from a playground finds
    # out here rather than by reading a plausible-looking wrong answer.
    if payload.model != model:
        logger.warning(
            "openai completion refused completion_id=%s requested_model=%s served_model=%s",
            completion_id,
            payload.model,
            model,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"The model {payload.model!r} does not exist. "
                f"This endpoint serves {model!r} only; see GET /v1/models."
            ),
        )

    # The agent owns its prompt: only user turns are read, and any system or
    # assistant message a client sends is dropped. Say so, because a client
    # replaying a full prompt would otherwise wonder where it went.
    ignored = [message.role for message in payload.messages if message.role != "user"]
    if ignored:
        logger.info(
            "openai completion ignoring %d non-user message(s) roles=%s completion_id=%s",
            len(ignored),
            sorted(set(ignored)),
            completion_id,
        )

    try:
        turn = await service.store_user_message(
            session,
            payload,
            header_session_uid=x_session_uid,
        )
        # The graph reads history through a separate async session. Commit the
        # new user turn before returning a stream or invoking the graph.
        await session.commit()
    except service.InvalidConversationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except service.SessionOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    response_headers = {"X-Session-UID": str(turn.session_uid)}
    created = int(time.time())
    if payload.stream:
        return StreamingResponse(
            _completion_events(
                turn,
                completion_id=completion_id,
                created=created,
                model=model,
            ),
            media_type="text/event-stream",
            headers={
                **response_headers,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        content = await service.answer(turn)
    except Exception as exc:
        logger.exception(
            "openai completion failed completion_id=%s session_uid=%s",
            completion_id,
            turn.session_uid,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The agent could not complete the response.",
        ) from exc

    response = ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=model,
        choices=[CompletionChoice(message=AssistantMessage(content=content))],
    )
    elapsed = (time.perf_counter() - started) * 1_000
    logger.info(
        "openai completion completed completion_id=%s session_uid=%s response_chars=%d "
        "elapsed_ms=%.1f",
        completion_id,
        turn.session_uid,
        len(content),
        elapsed,
    )
    return JSONResponse(
        content=response.model_dump(mode="json"),
        headers=response_headers,
    )
