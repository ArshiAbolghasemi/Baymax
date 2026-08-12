"""Knowledge base ingestion endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Path, status

from baymax.common.logging import correlation_id, get_logger
from baymax.db.dependencies import SessionDep
from baymax.knowledge_base import service
from baymax.knowledge_base.schemas import (
    ErrorResponse,
    KnowledgeBaseEntryCreate,
    KnowledgeBaseEntryRead,
    KnowledgeBaseEntryStatus,
)
from baymax.knowledge_base.tasks import index_knowledge_base_entry

logger = get_logger(__name__)

router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])


@router.post(
    "/entries",
    response_model=KnowledgeBaseEntryRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Store an answer with its questions and queue vector indexing",
    response_description=(
        "The entry as stored. `point_uid` is null on every pair — indexing has "
        "only been queued at this point."
    ),
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Empty answer, no questions, or too many questions.",
        }
    },
)
def create_entry(payload: KnowledgeBaseEntryCreate, session: SessionDep) -> KnowledgeBaseEntryRead:
    """Store an answer and the questions it answers.

    Questions are de-duplicated case-insensitively within the request, and
    question text already present in the database is reused rather than
    inserted again — the same question can serve several answers.

    Returns `202` as soon as Postgres has the entry. Use the returned
    `answer_uid` with `GET /knowledge-base/entries/{answer_uid}` to follow
    indexing, or `task_id` to inspect the Celery job.
    """
    logger.info("create entry requested questions=%d", len(payload.questions))

    answer_uid, questions, pairs = service.store_entry(session, payload)

    # Commit before enqueueing: the worker runs in another process and must not
    # be able to look for rows this transaction has not written yet.
    session.commit()
    logger.debug("committed answer uid=%s before enqueue", answer_uid)

    task = index_knowledge_base_entry.delay(str(answer_uid), correlation_id.get())
    logger.info("queued indexing task id=%s answer_uid=%s", task.id, answer_uid)

    return KnowledgeBaseEntryRead(
        answer_uid=answer_uid,
        questions=questions,
        pairs=pairs,
        task_id=task.id,
    )


@router.get(
    "/entries/{answer_uid}",
    response_model=KnowledgeBaseEntryStatus,
    summary="Inspect an entry and how much of it has been indexed",
    response_description="The stored entry with its per-pair indexing state.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No answer with this uid.",
        }
    },
)
def get_entry(
    session: SessionDep,
    answer_uid: uuid.UUID = Path(description="`answer_uid` returned when the entry was created."),
) -> KnowledgeBaseEntryStatus:
    """Report indexing progress for one entry.

    The entry is fully indexed when `indexed_pairs == total_pairs`; every pair
    then carries the `point_uid` of its Qdrant point.
    """
    try:
        return service.get_entry_status(session, answer_uid)
    except service.AnswerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
