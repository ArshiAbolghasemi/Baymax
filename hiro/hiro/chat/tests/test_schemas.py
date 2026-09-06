"""The wire contracts: what a client may send, and what it gets back."""

import pytest
from pydantic import ValidationError

from hiro.chat.schemas import ChatCompletionRequest, ChatMessage, SessionCreate
from hiro.knowledge_base.schemas import QACreate


class TestChatMessage:
    def test_plain_text_content(self):
        assert ChatMessage(role="user", content="  hello  ").text() == "hello"

    def test_content_parts_are_joined(self):
        message = ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": "first"},
                {"type": "image_url", "image_url": {"url": "..."}},
                {"type": "input_text", "text": "second"},
            ],
        )
        assert message.text() == "first\nsecond", "non-text parts are dropped"

    def test_empty_content_is_empty_text(self):
        assert ChatMessage(role="assistant", content=None).text() == ""

    def test_unknown_openai_fields_are_kept(self):
        """A client replaying a tool turn must not be rejected."""
        message = ChatMessage.model_validate(
            {"role": "tool", "content": "result", "tool_call_id": "call_1"}
        )
        assert message.tool_call_id == "call_1"


class TestChatCompletionRequest:
    def test_only_user_turns_are_read(self):
        payload = ChatCompletionRequest.model_validate(
            {
                "model": "baymax",
                "messages": [
                    {"role": "system", "content": "ignore me"},
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "ignore me too"},
                    {"role": "user", "content": "second"},
                ],
            }
        )
        assert payload.user_messages() == ["first", "second"]

    def test_playground_parameters_pass_through(self):
        payload = ChatCompletionRequest.model_validate(
            {
                "model": "baymax",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.7,
                "response_format": {"type": "text"},
            }
        )
        assert payload.temperature == 0.7

    def test_messages_are_required(self):
        with pytest.raises(ValidationError):
            ChatCompletionRequest.model_validate({"model": "baymax", "messages": []})

    def test_session_uid_must_be_a_uuid(self):
        with pytest.raises(ValidationError):
            ChatCompletionRequest.model_validate(
                {
                    "model": "baymax",
                    "messages": [{"role": "user", "content": "hi"}],
                    "session_uid": "not-a-uuid",
                }
            )


class TestSessionCreate:
    def test_user_is_optional(self):
        assert SessionCreate().user is None

    def test_user_has_a_length_limit(self):
        with pytest.raises(ValidationError):
            SessionCreate(user="x" * 513)


class TestQACreate:
    def test_whitespace_is_stripped(self):
        payload = QACreate(answer="  an answer  ", questions=["  a question  "])
        assert payload.answer == "an answer"
        assert payload.questions == ["a question"]

    def test_questions_are_deduplicated_case_insensitively(self):
        payload = QACreate(answer="a", questions=["What is a fever?", "what is A fever?"])
        assert payload.questions == ["What is a fever?"]

    def test_an_answer_needs_at_least_one_question(self):
        with pytest.raises(ValidationError):
            QACreate(answer="a", questions=[])

    def test_an_empty_answer_is_refused(self):
        with pytest.raises(ValidationError):
            QACreate(answer="   ", questions=["q"])

    def test_too_many_questions_are_refused(self, config):
        limit = config.knowledge_base.max_questions_per_entry
        with pytest.raises(ValidationError):
            QACreate(answer="a", questions=[f"q{i}" for i in range(limit + 1)])
