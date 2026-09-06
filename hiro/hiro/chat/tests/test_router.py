"""The HTTP surface: status codes, error codes, and the SSE frames."""

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hiro.chat import router as chat_router
from hiro.chat import service
from hiro.chat.agent.events import TextDelta, ToolCall, ToolResult
from hiro.db.dependencies import get_async_session

SESSION = uuid.uuid4()
USER = uuid.uuid4()


class FakeSession:
    """An async DB session that records commits and touches no database."""

    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(chat_router.router)
    app.dependency_overrides[get_async_session] = lambda: FakeSession()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def turn(monkeypatch):
    prepared = service.PreparedTurn(
        session_uid=SESSION, user_uid=USER, question="q", user_message_stored=True
    )

    async def store_user_message(session, payload, *, header_session_uid):
        return prepared

    monkeypatch.setattr(chat_router.service, "store_user_message", store_user_message)
    return prepared


def body(**kwargs):
    return {"model": "baymax", "messages": [{"role": "user", "content": "hi"}], **kwargs}


class TestModels:
    def test_one_model_is_advertised(self, client, config):
        response = client.get("/v1/models")
        assert response.status_code == 200
        assert [m["id"] for m in response.json()["data"]] == [config.chat.agent_model_name]


class TestSessions:
    def test_opening_a_conversation(self, client, monkeypatch):
        class Row:
            session_uid, user_uid, created_at = SESSION, USER, "2026-01-01T00:00:00Z"

        async def create_session(session, payload):
            return Row()

        monkeypatch.setattr(chat_router.service, "create_session", create_session)

        response = client.post("/v1/sessions", json={"user": "arshia"})
        assert response.status_code == 201
        assert response.json()["session_uid"] == str(SESSION)


class TestCompletionRefusals:
    def test_another_model_is_not_served(self, client, turn):
        response = client.post(
            "/v1/chat/completions",
            json=body(model="gpt-4o"),
            headers={"X-Session-UID": str(SESSION)},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "model_not_found"

    @pytest.mark.parametrize(
        ("error", "status", "code"),
        [
            (service.InvalidConversationError("no conversation"), 400, "invalid_request"),
            (service.UnknownSessionError("gone"), 404, "session_not_found"),
            (service.SessionOwnershipError("not yours"), 409, "session_owned_by_another_user"),
        ],
    )
    def test_service_errors_map_to_codes(self, client, monkeypatch, error, status, code):
        async def explode(session, payload, *, header_session_uid):
            raise error

        monkeypatch.setattr(chat_router.service, "store_user_message", explode)
        response = client.post("/v1/chat/completions", json=body())
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code

    def test_an_unknown_session_and_an_unknown_model_are_told_apart(self, client, monkeypatch):
        """Both are 404: only the code lets a client know which to recover from."""

        async def explode(session, payload, *, header_session_uid):
            raise service.UnknownSessionError("gone")

        monkeypatch.setattr(chat_router.service, "store_user_message", explode)
        session_404 = client.post("/v1/chat/completions", json=body()).json()
        model_404 = client.post("/v1/chat/completions", json=body(model="gpt-4o")).json()
        assert session_404["detail"]["code"] != model_404["detail"]["code"]


class TestCompletions:
    def test_a_non_streaming_reply(self, client, turn, monkeypatch, config):
        async def answer(prepared):
            return "an answer"

        monkeypatch.setattr(chat_router.service, "answer", answer)
        response = client.post("/v1/chat/completions", json=body())

        assert response.status_code == 200
        payload = response.json()
        assert payload["choices"][0]["message"]["content"] == "an answer"
        assert payload["model"] == config.chat.agent_model_name
        assert response.headers["X-Session-UID"] == str(SESSION)

    def test_a_failing_agent_does_not_leak_internals(self, client, turn, monkeypatch):
        async def explode(prepared):
            raise RuntimeError("qdrant exploded with credentials in the message")

        monkeypatch.setattr(chat_router.service, "answer", explode)
        response = client.post("/v1/chat/completions", json=body())
        assert response.status_code == 500
        assert "qdrant" not in response.text

    def test_the_stream_carries_text_tool_calls_and_results(self, client, turn, monkeypatch):
        async def stream(prepared):
            yield TextDelta("Let me check. ")
            yield ToolCall(id="c1", name="search_drug_label", arguments={"drug_name": "ibuprofen"})
            yield ToolResult(tool_call_id="c1", name="search_drug_label", content='{"status":"ok"}')
            yield TextDelta("It warns about bleeding.")

        monkeypatch.setattr(chat_router.service, "stream_reply", stream)
        response = client.post("/v1/chat/completions", json=body(stream=True))

        assert response.status_code == 200
        frames = [
            json.loads(line[5:])
            for line in response.text.splitlines()
            if line.startswith("data:") and line[5:].strip() != "[DONE]"
        ]
        deltas = [frame["choices"][0]["delta"] for frame in frames]

        assert deltas[0] == {"role": "assistant", "content": ""}, "the opening role frame"
        assert (
            "".join(d.get("content", "") for d in deltas)
            == "Let me check. It warns about bleeding."
        )

        call = next(d["tool_calls"][0] for d in deltas if "tool_calls" in d)
        assert call["function"]["name"] == "search_drug_label"
        assert json.loads(call["function"]["arguments"]) == {"drug_name": "ibuprofen"}

        result = next(d["tool_results"][0] for d in deltas if "tool_results" in d)
        assert result["tool_call_id"] == "c1"
        assert frames[-1]["choices"][0]["finish_reason"] == "stop"
        assert response.text.rstrip().endswith("data: [DONE]")

    def test_a_mid_stream_failure_becomes_an_error_frame(self, client, turn, monkeypatch):
        async def stream(prepared):
            yield TextDelta("starting")
            raise RuntimeError("boom")

        monkeypatch.setattr(chat_router.service, "stream_reply", stream)
        response = client.post("/v1/chat/completions", json=body(stream=True))

        frames = [
            json.loads(line[5:])
            for line in response.text.splitlines()
            if line.startswith("data:") and line[5:].strip() != "[DONE]"
        ]
        assert frames[-1]["error"]["code"] == "agent_generation_failed"
        assert response.text.rstrip().endswith("data: [DONE]"), "the stream is still closed"


class TestDeltaEncoding:
    def test_text_uses_the_standard_field(self):
        assert chat_router._delta(TextDelta("hi")) == {"content": "hi"}

    def test_a_tool_call_is_openai_shaped(self):
        delta = chat_router._delta(
            ToolCall(id="c1", name="search_genetics", arguments={"q": "BRCA1"})
        )
        call = delta["tool_calls"][0]
        assert call["type"] == "function" and call["id"] == "c1"
        assert json.loads(call["function"]["arguments"]) == {"q": "BRCA1"}

    def test_a_tool_result_travels_outside_the_standard(self):
        """OpenAI has no shape for a result the server produced itself."""
        delta = chat_router._delta(
            ToolResult(tool_call_id="c1", name="search_genetics", content="{}")
        )
        assert delta == {
            "tool_results": [{"tool_call_id": "c1", "name": "search_genetics", "content": "{}"}]
        }
