"""Prompts come from Phoenix, and nothing about them is hard-coded here."""

import pytest

from hiro.chat import prompts


class FakeVersion:
    def __init__(self, messages):
        self._messages = messages

    def format(self, *, variables):
        rendered = [
            {"role": role, "content": content.format(**variables)}
            for role, content in self._messages
        ]
        return {"messages": rendered, "model": "test-model"}


class FakePrompts:
    def __init__(self, versions=None, error=None):
        self.versions = versions or {}
        self.error = error
        self.asked: list[tuple] = []

    async def get(self, *, prompt_identifier, tag=None):
        self.asked.append((prompt_identifier, tag))
        if self.error:
            raise self.error
        return self.versions[prompt_identifier]


@pytest.fixture
def phoenix(monkeypatch):
    fake = FakePrompts(
        {
            "hiro-answer": FakeVersion(
                [("system", "You are Baymax."), ("user", "Question: {question}")]
            ),
            "hiro-blocked": FakeVersion([("user", "I can not process this request.")]),
        }
    )
    monkeypatch.setattr(prompts, "get_client", lambda: type("C", (), {"prompts": fake})())
    return fake


class TestGetMessages:
    async def test_variables_are_substituted_by_phoenix(self, phoenix):
        messages = await prompts.get_messages("hiro-answer", question="is ibuprofen safe?")
        assert [m.type for m in messages] == ["system", "human"]
        assert messages[1].content == "Question: is ibuprofen safe?"

    async def test_each_prompt_is_pinned_independently(self, phoenix, monkeypatch):
        """Only the prompt whose tag is set is pinned; the rest stay on latest."""
        from hiro.config import get_config

        monkeypatch.setenv("CHAT_PROMPT_ANSWER_TAG", "v0-1-0")
        get_config.cache_clear()

        await prompts.get_messages("hiro-answer", question="q")
        await prompts.get_text("hiro-blocked")

        assert phoenix.asked == [("hiro-answer", "v0-1-0"), ("hiro-blocked", None)]

    async def test_no_tag_means_the_latest_version(self, phoenix):
        await prompts.get_messages("hiro-answer", question="q")
        assert phoenix.asked[-1] == ("hiro-answer", None)

    async def test_a_missing_prompt_is_not_swallowed(self, monkeypatch):
        """There is no fallback wording: the run must fail loudly."""
        fake = FakePrompts(error=RuntimeError("no such prompt"))
        monkeypatch.setattr(prompts, "get_client", lambda: type("C", (), {"prompts": fake})())
        with pytest.raises(RuntimeError):
            await prompts.get_messages("hiro-answer", question="q")


class TestGetText:
    async def test_a_single_message_prompt_reads_as_a_string(self, phoenix):
        assert await prompts.get_text("hiro-blocked") == "I can not process this request."


class TestTracing:
    async def test_the_prompt_and_its_wording_are_traced(self, phoenix, spans):
        await prompts.get_messages("hiro-answer", question="is ibuprofen safe?")
        span = spans()["prompt hiro-answer"]
        assert span.attributes["prompt.identifier"] == "hiro-answer"
        assert span.attributes["hiro.retrieved"] == 2
        assert "You are Baymax." in span.attributes["retrieval.documents.0.document.content"]
