"""Chat endpoints: one WebSocket for output, plain HTTP for everything else."""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from baymax.chat import service
from baymax.chat.connections import connections
from baymax.chat.schemas import (
    MessageCreate,
    MessageRead,
    SessionCreate,
    SessionRead,
    StreamAccepted,
)
from baymax.common.logging import get_logger
from baymax.db.dependencies import AsyncSessionDep

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user_uid: Annotated[uuid.UUID, Query(description="Owner of this socket.")],
) -> None:
    """Receive-only channel: the server streams assistant replies down it.

    The client sends nothing meaningful here — chat messages go over HTTP. We
    still read in a loop because that is the only way Starlette surfaces a
    disconnect, and anything received is discarded.
    """
    await websocket.accept()
    connections.register(user_uid, websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("websocket disconnected for user %s", user_uid)
    except Exception:
        logger.info("websocket errored for user %s", user_uid, exc_info=True)
    finally:
        connections.unregister(user_uid, websocket)


@router.post(
    "/sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a conversation",
)
async def create_session(payload: SessionCreate, session: AsyncSessionDep) -> SessionRead:
    session_uid = await service.create_session(session, payload.user_uid)
    return SessionRead(session_uid=session_uid)


@router.post(
    "/sessions/{session_uid}/messages",
    response_model=StreamAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a user message and stream the reply over the WebSocket",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "No such session."},
        status.HTTP_409_CONFLICT: {"description": "No active websocket connection."},
    },
)
async def post_message(
    session_uid: uuid.UUID,
    payload: MessageCreate,
    session: AsyncSessionDep,
    background: BackgroundTasks,
) -> StreamAccepted:
    """Persist the user turn, then stream the reply.

    The user message is written before anything else, so it survives a failed
    generation. The reply is produced after this response is sent — the body is
    only an acknowledgement, the content arrives on the socket.
    """
    try:
        user_uid = await service.store_user_message(session, session_uid, payload.content)
    except service.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Commit before anything can fail: the user's turn is theirs and must not be
    # rolled back by a 409, and the background task opens its own session and
    # has to be able to read what we just wrote.
    await session.commit()

    try:
        service.ensure_connected(user_uid)
    except service.NoConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    background.add_task(service.stream_reply, session_uid, user_uid, payload.content)
    logger.info("queued reply stream for session %s", session_uid)

    return StreamAccepted()


@router.get(
    "/sessions/{session_uid}/messages",
    response_model=list[MessageRead],
    summary="Conversation history, oldest first",
)
async def get_messages(session_uid: uuid.UUID, session: AsyncSessionDep) -> list[MessageRead]:
    try:
        history = await service.get_history(session, session_uid)
    except service.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [MessageRead.model_validate(message) for message in history]
