"""Data access for answers, questions and their join rows.

Functions here never commit — the caller owns the transaction boundary.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from common.logging import get_logger
from knowledge_base.models import Answer, AnswerQuestion, Question

logger = get_logger(__name__)


def create_answer(session: Session, content: str) -> Answer:
    answer = Answer(content=content)
    session.add(answer)
    session.flush()
    logger.debug("inserted answer uid=%s chars=%d", answer.uid, len(content))
    return answer


def get_or_create_questions(session: Session, contents: Sequence[str]) -> list[Question]:
    """Resolve question texts to rows, inserting the ones we have not seen.

    Uses ``ON CONFLICT DO NOTHING`` so two concurrent requests submitting the
    same question cannot deadlock or raise a unique violation.
    """
    if not contents:
        return []

    # RETURNING yields only the rows that were actually inserted, which is the
    # one reliable way to count new-vs-reused (rowcount is -1 here).
    inserted = session.scalars(
        pg_insert(Question)
        .values([{"uid": uuid.uuid4(), "content": content} for content in contents])
        .on_conflict_do_nothing(index_elements=[Question.content])
        .returning(Question.uid)
    ).all()
    session.flush()

    logger.debug(
        "questions requested=%d inserted=%d reused=%d",
        len(contents),
        len(inserted),
        len(contents) - len(inserted),
    )

    rows = session.scalars(select(Question).where(Question.content.in_(contents))).all()
    by_content = {row.content: row for row in rows}
    # Preserve the caller's ordering.
    return [by_content[content] for content in contents]


def link_questions_to_answer(
    session: Session, answer: Answer, questions: Iterable[Question]
) -> list[AnswerQuestion]:
    """Create the join rows for an answer, ignoring pairs that already exist."""
    questions = list(questions)
    if not questions:
        return []

    session.execute(
        pg_insert(AnswerQuestion)
        .values(
            [
                {
                    "uid": uuid.uuid4(),
                    "answer_uid": answer.uid,
                    "question_uid": question.uid,
                }
                for question in questions
            ]
        )
        .on_conflict_do_nothing(constraint="uq_answer_questions_pair"),
    )
    session.flush()

    question_uids = [question.uid for question in questions]
    pairs = list(
        session.scalars(
            select(AnswerQuestion).where(
                AnswerQuestion.answer_uid == answer.uid,
                AnswerQuestion.question_uid.in_(question_uids),
            )
        ).all()
    )
    logger.debug("linked %d pair(s) to answer uid=%s", len(pairs), answer.uid)
    return pairs


def get_answer(session: Session, answer_uid: uuid.UUID) -> Answer | None:
    return session.get(Answer, answer_uid)


def list_pairs(session: Session, answer_uid: uuid.UUID) -> list[AnswerQuestion]:
    return list(
        session.scalars(
            select(AnswerQuestion)
            .where(AnswerQuestion.answer_uid == answer_uid)
            .order_by(AnswerQuestion.created_at)
        ).all()
    )


def list_unindexed_pairs(session: Session, answer_uid: uuid.UUID) -> list[AnswerQuestion]:
    """Pairs still missing a Qdrant point, with both sides eagerly loaded.

    Filtering on ``point_uid IS NULL`` is what makes the indexing task safe to
    retry: work already committed is simply not selected again.
    """
    pairs = list(
        session.scalars(
            select(AnswerQuestion)
            .where(
                AnswerQuestion.answer_uid == answer_uid,
                AnswerQuestion.point_uid.is_(None),
            )
            .options(
                selectinload(AnswerQuestion.question),
                selectinload(AnswerQuestion.answer),
            )
            .order_by(AnswerQuestion.created_at)
        ).all()
    )
    logger.debug("answer uid=%s has %d unindexed pair(s)", answer_uid, len(pairs))
    return pairs


def mark_pairs_indexed(session: Session, point_uids: dict[uuid.UUID, uuid.UUID]) -> None:
    """Attach Qdrant point uids to their join rows.

    ``point_uids`` maps ``answer_questions.uid`` to the point written to Qdrant.
    """
    if not point_uids:
        return

    now = datetime.now(UTC)
    # ORM bulk update by primary key: one executemany round trip for all pairs.
    session.execute(
        update(AnswerQuestion),
        [
            {"uid": pair_uid, "point_uid": point_uid, "indexed_at": now}
            for pair_uid, point_uid in point_uids.items()
        ],
    )
    logger.debug("stamped point_uid on %d pair(s)", len(point_uids))
