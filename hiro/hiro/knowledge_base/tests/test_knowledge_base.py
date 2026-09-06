"""Knowledge base ingestion and indexing, without Postgres or Qdrant."""

import uuid
from dataclasses import dataclass, field

from hiro.knowledge_base import service
from hiro.knowledge_base.schemas import QACreate


@dataclass
class Answer:
    uid: uuid.UUID = field(default_factory=uuid.uuid4)
    content: str = "an answer"


@dataclass
class Question:
    uid: uuid.UUID = field(default_factory=uuid.uuid4)
    content: str = "a question"


@dataclass
class Pair:
    uid: uuid.UUID = field(default_factory=uuid.uuid4)
    answer_uid: uuid.UUID = field(default_factory=uuid.uuid4)
    question_uid: uuid.UUID = field(default_factory=uuid.uuid4)
    point_uid: uuid.UUID | None = None


class TestPointIdentity:
    def test_a_pair_always_maps_to_the_same_point(self, config):
        """A retried indexing task must rewrite its point, not orphan it."""
        pair = Pair()
        assert service.point_uid_for(pair) == service.point_uid_for(pair)

    def test_different_pairs_map_to_different_points(self, config):
        assert service.point_uid_for(Pair()) != service.point_uid_for(Pair())

    def test_the_namespace_decides_the_point(self, monkeypatch, config):
        from hiro.config import get_config

        pair = Pair()
        before = service.point_uid_for(pair)
        monkeypatch.setenv("KNOWLEDGE_BASE_POINT_NAMESPACE", str(uuid.uuid4()))
        get_config.cache_clear()
        assert service.point_uid_for(pair) != before


class TestPairText:
    def test_both_sides_are_embedded_together(self):
        text = service.build_pair_text("What is a fever?", "A rise in body temperature.")
        assert text == "question: What is a fever?\nanswer: A rise in body temperature."


class TestStoreQa:
    def test_the_answer_its_questions_and_the_links_are_written(self, monkeypatch):
        answer, questions = Answer(), [Question(), Question()]
        pairs = [Pair(answer_uid=answer.uid, question_uid=q.uid) for q in questions]
        calls = []

        class FakeRepo:
            def create_answer(self, session, content):
                calls.append(("answer", content))
                return answer

            def get_or_create_questions(self, session, contents):
                calls.append(("questions", list(contents)))
                return questions

            def link_questions_to_answer(self, session, a, q):
                calls.append(("link", a.uid))
                return pairs

        monkeypatch.setattr(service, "repo", FakeRepo())
        payload = QACreate(answer="an answer", questions=["first?", "second?"])

        answer_uid, read_questions, read_pairs = service.store_qa(object(), payload)

        assert answer_uid == answer.uid
        assert len(read_questions) == 2 and len(read_pairs) == 2
        assert [name for name, _ in calls] == ["answer", "questions", "link"]

    def test_pairs_come_back_unindexed(self, monkeypatch):
        """Qdrant is written by the worker: the API only promises Postgres."""
        answer, question, pair = Answer(), Question(), Pair()

        class FakeRepo:
            create_answer = staticmethod(lambda session, content: answer)
            get_or_create_questions = staticmethod(lambda session, contents: [question])
            link_questions_to_answer = staticmethod(lambda session, a, q: [pair])

        monkeypatch.setattr(service, "repo", FakeRepo())
        _, _, pairs = service.store_qa(object(), QACreate(answer="a", questions=["q"]))
        assert pairs[0].point_uid is None
