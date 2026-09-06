"""Who a request is for, and which conversation it names."""

import uuid

from hiro.chat.schemas import ChatCompletionRequest
from hiro.chat.session_resolution import derive_user_uid, resolve_session_uid


def request(**kwargs) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {"model": "baymax", "messages": [{"role": "user", "content": "hi"}], **kwargs}
    )


class TestUserIdentity:
    def test_a_uuid_is_kept_as_is(self):
        given = uuid.uuid4()
        assert derive_user_uid(str(given)) == given

    def test_any_other_string_hashes_to_a_stable_uuid(self, config):
        first = derive_user_uid("arshia@example.com")
        assert first == derive_user_uid("arshia@example.com")
        assert first != derive_user_uid("someone@example.com")

    def test_no_identity_is_one_shared_anonymous_user(self, config):
        assert derive_user_uid(None) == derive_user_uid("")

    def test_the_namespace_decides_the_identity(self, monkeypatch):
        from hiro.config import get_config

        before = derive_user_uid("arshia")
        monkeypatch.setenv("CHAT_SESSION_NAMESPACE", str(uuid.uuid4()))
        get_config.cache_clear()
        assert derive_user_uid("arshia") != before


class TestSessionResolution:
    def test_header_wins_over_body(self):
        header, body = uuid.uuid4(), uuid.uuid4()
        resolved = resolve_session_uid(request(session_uid=str(body)), header_session_uid=header)
        assert resolved == header

    def test_body_is_used_when_there_is_no_header(self):
        body = uuid.uuid4()
        assert resolve_session_uid(request(session_uid=str(body)), header_session_uid=None) == body

    def test_naming_nothing_resolves_to_nothing(self):
        """The endpoint must refuse, not invent a conversation."""
        assert resolve_session_uid(request(), header_session_uid=None) is None
