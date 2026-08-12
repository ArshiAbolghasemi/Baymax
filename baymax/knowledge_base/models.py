"""ORM models for the knowledge base.

Every row is identified by a UUID ``uid`` primary key — the same value that
travels into Qdrant payloads, so a point can always be traced back to its
Postgres record without a lookup table.

An answer is reusable across many questions and a question may (over time) be
attached to more than one answer, so the two are joined through
``answer_questions``. That join row is also the unit that gets indexed in
Qdrant, which is why ``point_uid`` lives there rather than on either side.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from baymax.db.base import Base, uid_fk_type, uid_pk


class Answer(Base):
    __tablename__ = "answers"

    uid: Mapped[uuid.UUID] = uid_pk()
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    links: Mapped[list[AnswerQuestion]] = relationship(
        back_populates="answer", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    uid: Mapped[uuid.UUID] = uid_pk()
    # Unique so the same phrasing is stored once and can be re-pointed at
    # another answer through the join table instead of being duplicated.
    content: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    links: Mapped[list[AnswerQuestion]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class AnswerQuestion(Base):
    """A question/answer pair — one row here becomes one point in Qdrant."""

    __tablename__ = "answer_questions"
    __table_args__ = (
        UniqueConstraint("answer_uid", "question_uid", name="uq_answer_questions_pair"),
        # Partial index: the indexing task only ever scans for un-indexed pairs.
        Index(
            "ix_answer_questions_pending",
            "answer_uid",
            postgresql_where=text("point_uid IS NULL"),
        ),
    )

    uid: Mapped[uuid.UUID] = uid_pk()
    answer_uid: Mapped[uuid.UUID] = mapped_column(
        uid_fk_type(),
        ForeignKey("answers.uid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_uid: Mapped[uuid.UUID] = mapped_column(
        uid_fk_type(),
        ForeignKey("questions.uid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The Qdrant point for this pair. NULL until the indexing task has run.
    point_uid: Mapped[uuid.UUID | None] = mapped_column(uid_fk_type(), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    answer: Mapped[Answer] = relationship(back_populates="links")
    question: Mapped[Question] = relationship(back_populates="links")

    @property
    def is_indexed(self) -> bool:
        return self.point_uid is not None
