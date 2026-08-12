"""Pydantic contracts for knowledge base ingestion.

Each model carries a ``json_schema_extra`` example so Swagger UI's "Try it out"
form is pre-filled with something realistic rather than ``"string"``.
"""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from baymax.config import get_config

NonEmptyText = Annotated[str, Field(min_length=1, max_length=32_000)]

_ANSWER_EXAMPLE = (
    "A fever is a temporary rise in body temperature, usually above 38 C (100.4 F). "
    "It is most often a sign that the body is fighting an infection."
)
_QUESTIONS_EXAMPLE = [
    "What is a fever?",
    "How do I know if I have a fever?",
    "What temperature counts as a fever?",
]
_ANSWER_UID_EXAMPLE = "3f2a9c14-6d8e-4b1a-9f77-2c5e8d0a41b3"
_QUESTION_UID_EXAMPLE = "8c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
_PAIR_UID_EXAMPLE = "b7e4d2a1-9c3f-4e5b-8a6d-1f2e3c4b5a60"
_POINT_UID_EXAMPLE = "d41f8c2b-5e7a-5b3c-9d1e-6f8a2b4c7d90"


class QACreate(BaseModel):
    """One answer plus every question it is meant to satisfy."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"answer": _ANSWER_EXAMPLE, "questions": _QUESTIONS_EXAMPLE}]
        }
    )

    answer: NonEmptyText = Field(description="The answer text. Stored verbatim.")
    questions: Annotated[list[NonEmptyText], Field(min_length=1)] = Field(
        description=(
            "Questions this answer satisfies. Duplicates are dropped "
            "case-insensitively; each surviving question becomes one Qdrant point."
        )
    )

    @field_validator("answer", "questions", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def _drop_duplicate_questions(self) -> Self:
        seen: set[str] = set()
        unique: list[str] = []
        for question in self.questions:
            key = question.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(question)

        limit = get_config().knowledge_base.max_questions_per_entry
        if len(unique) > limit:
            msg = f"at most {limit} questions per entry, got {len(unique)}"
            raise ValueError(msg)

        self.questions = unique
        return self


class QuestionRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [{"uid": _QUESTION_UID_EXAMPLE, "content": _QUESTIONS_EXAMPLE[0]}]
        },
    )

    uid: uuid.UUID
    content: str


class PairRead(BaseModel):
    """A question/answer join row and its Qdrant point, once indexed."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "uid": _PAIR_UID_EXAMPLE,
                    "question_uid": _QUESTION_UID_EXAMPLE,
                    "answer_uid": _ANSWER_UID_EXAMPLE,
                    "point_uid": _POINT_UID_EXAMPLE,
                    "indexed_at": "2026-08-13T09:15:00Z",
                }
            ]
        },
    )

    uid: uuid.UUID = Field(description="Join row uid — the unit that becomes a Qdrant point.")
    question_uid: uuid.UUID
    answer_uid: uuid.UUID
    point_uid: uuid.UUID | None = Field(
        default=None, description="Qdrant point id. Null until the indexing task has run."
    )
    indexed_at: datetime | None = Field(
        default=None, description="When the point was written. Null while pending."
    )


class QARead(BaseModel):
    """Returned by the create endpoint, before indexing has run."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "answer_uid": _ANSWER_UID_EXAMPLE,
                    "questions": [{"uid": _QUESTION_UID_EXAMPLE, "content": _QUESTIONS_EXAMPLE[0]}],
                    "pairs": [
                        {
                            "uid": _PAIR_UID_EXAMPLE,
                            "question_uid": _QUESTION_UID_EXAMPLE,
                            "answer_uid": _ANSWER_UID_EXAMPLE,
                            "point_uid": None,
                            "indexed_at": None,
                        }
                    ],
                    "task_id": "2adea4db-c3f8-4178-81a1-4faeda65c94f",
                }
            ]
        }
    )

    answer_uid: uuid.UUID
    questions: list[QuestionRead]
    pairs: list[PairRead]
    task_id: str = Field(description="Celery task id for the queued indexing job.")


class QAStatus(BaseModel):
    """Indexing progress for a stored entry."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "answer_uid": _ANSWER_UID_EXAMPLE,
                    "answer": _ANSWER_EXAMPLE,
                    "total_pairs": 3,
                    "indexed_pairs": 3,
                    "pairs": [
                        {
                            "uid": _PAIR_UID_EXAMPLE,
                            "question_uid": _QUESTION_UID_EXAMPLE,
                            "answer_uid": _ANSWER_UID_EXAMPLE,
                            "point_uid": _POINT_UID_EXAMPLE,
                            "indexed_at": "2026-08-13T09:15:00Z",
                        }
                    ],
                }
            ]
        }
    )

    answer_uid: uuid.UUID
    answer: str
    total_pairs: int = Field(description="Question/answer pairs stored for this answer.")
    indexed_pairs: int = Field(description="Pairs already written to Qdrant.")
    pairs: list[PairRead]

    @property
    def is_fully_indexed(self) -> bool:
        return self.total_pairs == self.indexed_pairs


class ErrorResponse(BaseModel):
    """FastAPI's error envelope, declared so it appears in the schema."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"detail": f"answer {_ANSWER_UID_EXAMPLE} not found"}]}
    )

    detail: str
