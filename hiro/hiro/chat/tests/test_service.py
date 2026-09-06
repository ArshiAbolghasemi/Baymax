"""Turn orchestration: which conversation, whose, and what gets persisted."""

import uuid
from dataclasses import dataclass

import pytest

from hiro.chat import service
from hiro.chat.agent.events import TextDelta, ToolCall, ToolResult
from hiro.chat.schemas import ChatCompletionRequest, SessionCreate

SESSION = uuid.uuid4()
USER = uuid.uuid4()


@dataclass
class Row:
    session_uid: uuid.UUID
    user_uid: uuid.UUID
    created_at: object = None


@dataclass
class Message:
    role: str
    content: str


class FakeRepo:
    """The repository, reduced to what the service asks of it."""

    def __init__(self, session_row=None, latest=None):
        self.session_row = session_row
        self.latest = latest
        self.added: list[tuple] = []
        self.created: list[uuid.UUID] = []

    async def get_session_for_update(self, session, session_uid):
        return self.session_row

    async def get_latest_message(self, session, session_uid):
        return self.latest

    async def add_message(self, session, session_uid, role, content):
        self.added.append((session_uid, role, content))

    async def create_session(self, session, user_uid, **kwargs):
        self.created.append(user_uid)
        return Row(session_uid=SESSION, user_uid=user_uid)


@pytest.fixture
def repo(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(service, "repo", fake)
    return fake


def request(**kwargs) -> ChatCompletionRequest:
    body = {"model": "baymax", "messages": [{"role": "user", "content": "is ibuprofen safe?"}]}
    return ChatCompletionRequest.model_validate({**body, **kwargs})


class TestCreateSession:
    async def test_a_session_is_created_for_an_anonymous_user(self, repo, config):
        row = await service.create_session(object(), SessionCreate())
        assert row.session_uid == SESSION
        assert repo.created == [service.derive_user_uid(None)]

    async def test_a_named_user_gets_their_own_identity(self, repo):
        await service.create_session(object(), SessionCreate(user="arshia"))
        assert repo.created == [service.derive_user_uid("arshia")]


class TestStoreUserMessage:
    async def test_a_conversation_must_be_named(self, repo):
        """Completions never create a session — that is POST /v1/sessions."""
        with pytest.raises(service.InvalidConversationError, match="POST /v1/sessions"):
            await service.store_user_message(object(), request(), header_session_uid=None)

    async def test_an_unknown_conversation_is_refused(self, repo):
        repo.session_row = None
        with pytest.raises(service.UnknownSessionError):
            await service.store_user_message(object(), request(), header_session_uid=SESSION)

    async def test_a_request_without_a_user_turn_is_refused(self, repo):
        repo.session_row = Row(SESSION, USER)
        payload = ChatCompletionRequest.model_validate(
            {"model": "baymax", "messages": [{"role": "system", "content": "only a system turn"}]}
        )
        with pytest.raises(service.InvalidConversationError):
            await service.store_user_message(object(), payload, header_session_uid=SESSION)

    async def test_an_over_long_message_is_refused(self, repo):
        repo.session_row = Row(SESSION, USER)
        payload = request(messages=[{"role": "user", "content": "x" * 40_000}])
        with pytest.raises(service.InvalidConversationError, match="32000"):
            await service.store_user_message(object(), payload, header_session_uid=SESSION)

    async def test_another_users_conversation_is_refused(self, repo):
        repo.session_row = Row(SESSION, USER)
        with pytest.raises(service.SessionOwnershipError):
            await service.store_user_message(
                object(), request(user="someone-else"), header_session_uid=SESSION
            )

    async def test_ownership_is_only_checked_when_the_client_says_who_it_is(self, repo):
        """A client with no login must still be able to use its own session."""
        repo.session_row = Row(SESSION, USER)
        turn = await service.store_user_message(object(), request(), header_session_uid=SESSION)
        assert turn.user_uid == USER

    async def test_the_newest_user_turn_is_stored(self, repo):
        repo.session_row = Row(SESSION, USER)
        payload = request(
            messages=[
                {"role": "user", "content": "an earlier question"},
                {"role": "assistant", "content": "an earlier answer"},
                {"role": "user", "content": "the new question"},
            ]
        )
        turn = await service.store_user_message(object(), payload, header_session_uid=SESSION)

        assert turn.question == "the new question"
        assert repo.added == [(SESSION, "user", "the new question")]
        assert turn.user_message_stored is True

    async def test_replayed_history_is_not_copied_into_our_tables(self, repo):
        """Regenerating the same unanswered turn must not insert it twice."""
        repo.session_row = Row(SESSION, USER)
        repo.latest = Message(role="user", content="is ibuprofen safe?")

        turn = await service.store_user_message(object(), request(), header_session_uid=SESSION)

        assert repo.added == []
        assert turn.user_message_stored is False


class TestStreamReply:
    @staticmethod
    def turn():
        return service.PreparedTurn(
            session_uid=SESSION, user_uid=USER, question="q", user_message_stored=True
        )

    async def test_events_pass_through_and_the_text_is_persisted(self, monkeypatch):
        events = [
            ToolCall(id="c1", name="search_drug_label", arguments={}),
            ToolResult(tool_call_id="c1", name="search_drug_label", content="{}"),
            TextDelta("The label "),
            TextDelta("warns."),
        ]

        async def stream(question, session_uid):
            for event in events:
                yield event

        stored: list[tuple] = []

        async def store(session_uid, content):
            stored.append((session_uid, content))

        monkeypatch.setattr(service, "stream_answer", stream)
        monkeypatch.setattr(service, "_store_assistant_message", store)

        assert [e async for e in service.stream_reply(self.turn())] == events
        assert stored == [(SESSION, "The label warns.")], "only text is persisted"

    async def test_a_failed_generation_persists_nothing(self, monkeypatch):
        async def stream(question, session_uid):
            yield TextDelta("half an ")
            raise RuntimeError("the model died")

        stored = []
        monkeypatch.setattr(service, "stream_answer", stream)
        monkeypatch.setattr(service, "_store_assistant_message", lambda *a: stored.append(a))

        with pytest.raises(RuntimeError):
            async for _ in service.stream_reply(self.turn()):
                pass
        assert stored == [], "a partial reply is not an answer"

    async def test_the_non_streaming_answer_is_text_only(self, monkeypatch):
        async def stream(question, session_uid):
            yield ToolCall(id="c1", name="search_genetics", arguments={})
            yield TextDelta("hello ")
            yield TextDelta("world")

        monkeypatch.setattr(service, "stream_answer", stream)
        monkeypatch.setattr(service, "_store_assistant_message", _noop)

        assert await service.answer(self.turn()) == "hello world"

    async def test_the_tools_chosen_are_recorded_on_the_turn(self, monkeypatch, spans):
        async def stream(question, session_uid):
            yield ToolCall(id="c1", name="search_drug_label", arguments={})
            yield ToolCall(id="c2", name="search_drug_safety", arguments={})
            yield TextDelta("done")

        monkeypatch.setattr(service, "stream_answer", stream)
        monkeypatch.setattr(service, "_store_assistant_message", _noop)

        async for _ in service.stream_reply(self.turn()):
            pass

        turn_span = spans()["chat turn"]
        assert turn_span.attributes["llm.tools.selected"] == (
            "search_drug_label",
            "search_drug_safety",
        )
        assert turn_span.attributes["session.id"] == str(SESSION)
        assert turn_span.attributes["output.value"] == "done"


async def _noop(*args, **kwargs):
    return None
