"""Knowledge base ingestion: write to Postgres, then index pairs in Qdrant."""

import uuid

from qdrant_client.models import PointStruct
from sqlalchemy.orm import Session

from baymax.clients.embedding import EmbeddingClient
from baymax.clients.vector_store import VectorStore
from baymax.common.logging import get_logger, log_duration
from baymax.config import get_config
from baymax.knowledge_base import repository as repo
from baymax.knowledge_base.models import AnswerQuestion
from baymax.knowledge_base.schemas import (
    KnowledgeBaseEntryCreate,
    KnowledgeBaseEntryStatus,
    PairRead,
    QuestionRead,
)

logger = get_logger(__name__)


class AnswerNotFoundError(LookupError):
    """The requested answer does not exist."""


def point_uid_for(pair: AnswerQuestion) -> uuid.UUID:
    """Derive the pair's Qdrant point uid.

    uuid5 of the join row uid rather than random, so a retried indexing task
    rewrites the same point instead of orphaning the previous one.
    """
    return uuid.uuid5(get_config().knowledge_base.point_namespace, str(pair.uid))


def build_pair_text(question: str, answer: str) -> str:
    """Compose the text that represents a question/answer pair to the embedder."""
    return f"question: {question}\nanswer: {answer}"


def store_entry(
    session: Session, payload: KnowledgeBaseEntryCreate
) -> tuple[uuid.UUID, list[QuestionRead], list[PairRead]]:
    """Persist the answer, its questions and the join rows.

    Returns the uids the caller needs; the pairs come back un-indexed
    (``point_uid`` is NULL) because Qdrant is written by the Celery task.
    """
    with log_duration(logger, "store entry", questions=len(payload.questions)):
        answer = repo.create_answer(session, payload.answer)
        questions = repo.get_or_create_questions(session, payload.questions)
        pairs = repo.link_questions_to_answer(session, answer, questions)

    logger.info(
        "stored answer uid=%s questions=%d pairs=%d",
        answer.uid,
        len(questions),
        len(pairs),
    )
    return (
        answer.uid,
        [QuestionRead.model_validate(question) for question in questions],
        [PairRead.model_validate(pair) for pair in pairs],
    )


def index_entry(
    session: Session,
    answer_uid: uuid.UUID,
    *,
    embedding_client: EmbeddingClient,
    vector_store: VectorStore,
) -> int:
    """Embed and upsert every not-yet-indexed pair of an answer.

    Returns the number of pairs indexed. Idempotent: pairs that already carry a
    ``point_uid`` are skipped, so a retry after a partial failure resumes rather
    than duplicating work.
    """
    pairs = repo.list_unindexed_pairs(session, answer_uid)
    if not pairs:
        logger.info("nothing to index for answer uid=%s", answer_uid)
        return 0

    logger.info("indexing answer uid=%s pairs=%d", answer_uid, len(pairs))

    texts = [build_pair_text(pair.question.content, pair.answer.content) for pair in pairs]
    vectors = embedding_client.embed(texts)

    points = [
        PointStruct(
            id=str(point_uid_for(pair)),
            vector=vector,
            payload={
                "pair_uid": str(pair.uid),
                "answer_uid": str(pair.answer_uid),
                "question_uid": str(pair.question_uid),
                "question": pair.question.content,
                "answer": pair.answer.content,
            },
        )
        for pair, vector in zip(pairs, vectors, strict=True)
    ]

    vector_store.upsert(points)
    # Only recorded after Qdrant has acknowledged the write.
    repo.mark_pairs_indexed(session, {pair.uid: point_uid_for(pair) for pair in pairs})

    logger.info(
        "indexed answer uid=%s pairs=%d collection=%s",
        answer_uid,
        len(points),
        vector_store.collection,
    )
    return len(points)


def get_entry_status(session: Session, answer_uid: uuid.UUID) -> KnowledgeBaseEntryStatus:
    answer = repo.get_answer(session, answer_uid)
    if answer is None:
        logger.info("answer uid=%s not found", answer_uid)
        msg = f"answer {answer_uid} not found"
        raise AnswerNotFoundError(msg)

    pairs = repo.list_pairs(session, answer_uid)
    indexed = sum(1 for pair in pairs if pair.is_indexed)
    logger.debug("answer uid=%s indexed=%d/%d", answer_uid, indexed, len(pairs))

    return KnowledgeBaseEntryStatus(
        answer_uid=answer.uid,
        answer=answer.content,
        total_pairs=len(pairs),
        indexed_pairs=indexed,
        pairs=[PairRead.model_validate(pair) for pair in pairs],
    )
