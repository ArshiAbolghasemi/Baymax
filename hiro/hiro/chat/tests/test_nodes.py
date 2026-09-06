"""Each step of the workflow, with its models and stores faked out."""

import uuid
from importlib import import_module

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# ``nodes/__init__`` re-exports each node *function* under the module's own
# name, so a plain import gets the function. These tests need the modules, to
# patch what each one reaches for.
answer_node = import_module("hiro.chat.agent.nodes.answer")
blocked_node = import_module("hiro.chat.agent.nodes.blocked")
guardrail_node = import_module("hiro.chat.agent.nodes.guardrail")
documents_node = import_module("hiro.chat.agent.nodes.retrieve_documents")
history_node = import_module("hiro.chat.agent.nodes.retrieve_history")
instructions_node = import_module("hiro.chat.agent.nodes.retrieve_instructions")

QUESTION = "is ibuprofen safe?"
SESSION = uuid.uuid4()


class FakeModel:
    """Stands in for ChatOpenAI: returns a canned reply, or raises."""

    def __init__(self, reply=None, error=None):
        self._reply, self._error = reply, error
        self.calls: list[dict] = []

    async def ainvoke(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self._error:
            raise self._error
        return self._reply


@pytest.fixture
def prompt(monkeypatch):
    """Phoenix, reduced to the two messages a prompt renders to."""

    async def get_messages(identifier, **variables):
        return [
            SystemMessage(content=f"system:{identifier}"),
            HumanMessage(content="|".join(f"{k}={v}" for k, v in sorted(variables.items()))),
        ]

    async def get_text(identifier):
        return f"text:{identifier}"

    for module in (guardrail_node, blocked_node, answer_node):
        monkeypatch.setattr(module.prompts, "get_messages", get_messages, raising=False)
        monkeypatch.setattr(module.prompts, "get_text", get_text, raising=False)
    return get_messages


class TestGuardrail:
    async def test_a_leading_one_allows_the_question(self, prompt, monkeypatch):
        monkeypatch.setattr(
            guardrail_node, "get_guardrail_model", lambda: FakeModel(AIMessage(content="1"))
        )
        assert await guardrail_node.guardrail({"question": QUESTION}) == {"allowed": True}

    @pytest.mark.parametrize("verdict", ["0", "no", "", "I think this is medical"])
    async def test_anything_else_blocks(self, prompt, monkeypatch, verdict):
        monkeypatch.setattr(
            guardrail_node, "get_guardrail_model", lambda: FakeModel(AIMessage(content=verdict))
        )
        assert await guardrail_node.guardrail({"question": QUESTION}) == {"allowed": False}

    async def test_a_failing_classifier_blocks(self, prompt, monkeypatch):
        """An endpoint that is down cannot admit a non-medical question."""
        monkeypatch.setattr(
            guardrail_node, "get_guardrail_model", lambda: FakeModel(error=RuntimeError("down"))
        )
        assert await guardrail_node.guardrail({"question": QUESTION}) == {"allowed": False}

    async def test_an_unfetchable_prompt_blocks(self, monkeypatch):
        async def explode(identifier, **variables):
            raise RuntimeError("phoenix is down")

        monkeypatch.setattr(guardrail_node.prompts, "get_messages", explode)
        assert await guardrail_node.guardrail({"question": QUESTION}) == {"allowed": False}


class TestBlocked:
    async def test_the_refusal_is_fetched_never_generated(self, prompt, config):
        update = await blocked_node.blocked({"question": QUESTION})
        assert update == {"answer": f"text:{config.chat.prompt_blocked}"}


class TestAnswerPrompt:
    async def test_context_is_folded_into_the_prompt(self, prompt):
        messages = await answer_node.build_answer_messages(
            {
                "question": QUESTION,
                "instructions": ["Name the dose form."],
                "documents": ["Ibuprofen is an NSAID."],
                "history": ["what is a fever?"],
            }
        )
        rendered = messages[1].content
        assert "instructions=- Name the dose form." in rendered
        assert "documents=[1] Ibuprofen is an NSAID." in rendered
        assert "history=- what is a fever?" in rendered
        assert f"question={QUESTION}" in rendered

    async def test_empty_context_uses_the_stand_ins(self, prompt, config):
        messages = await answer_node.build_answer_messages({"question": QUESTION})
        rendered = messages[1].content
        assert f"instructions=text:{config.chat.prompt_no_instructions}" in rendered
        assert f"documents=text:{config.chat.prompt_no_documents}" in rendered
        assert f"history=text:{config.chat.prompt_no_history}" in rendered

    async def test_documents_are_numbered_for_citation(self, prompt):
        messages = await answer_node.build_answer_messages(
            {"question": QUESTION, "documents": ["first", "second"]}
        )
        assert "[1] first" in messages[1].content
        assert "[2] second" in messages[1].content


class TestAnswerStep:
    async def test_the_first_pass_returns_the_whole_prompt_and_the_reply(self, prompt, monkeypatch):
        model = FakeModel(AIMessage(content="an answer"))
        monkeypatch.setattr(answer_node, "get_answer_model", lambda: model)
        monkeypatch.setattr(answer_node, "get_answer_tool_schemas", _no_tools)

        update = await answer_node.answer({"question": QUESTION})

        assert update["answer"] == "an answer"
        assert len(update["messages"]) == 3, "prompt (2) plus the reply"

    async def test_a_later_pass_appends_only_the_reply(self, prompt, monkeypatch):
        model = FakeModel(AIMessage(content="final"))
        monkeypatch.setattr(answer_node, "get_answer_model", lambda: model)
        monkeypatch.setattr(answer_node, "get_answer_tool_schemas", _no_tools)

        update = await answer_node.answer(
            {"question": QUESTION, "messages": [HumanMessage(content="earlier")]}
        )
        assert update["messages"] == [AIMessage(content="final")]

    async def test_a_tool_request_is_not_an_answer(self, prompt, monkeypatch):
        """``answer`` is only set when the model stopped calling tools."""
        reply = AIMessage(
            content="", tool_calls=[{"name": "search_drug_label", "args": {}, "id": "c1"}]
        )
        monkeypatch.setattr(answer_node, "get_answer_model", lambda: FakeModel(reply))
        monkeypatch.setattr(answer_node, "get_answer_tool_schemas", _no_tools)

        update = await answer_node.answer({"question": QUESTION})
        assert "answer" not in update
        assert answer_node._selected_tools(update) == ["search_drug_label"]

    async def test_the_tools_are_offered_to_the_model(self, prompt, monkeypatch):
        model = FakeModel(AIMessage(content="hi"))
        monkeypatch.setattr(answer_node, "get_answer_model", lambda: model)

        async def schemas():
            return [{"type": "function", "function": {"name": "search_genetics"}}]

        monkeypatch.setattr(answer_node, "get_answer_tool_schemas", schemas)
        await answer_node.answer({"question": QUESTION})

        assert model.calls[0]["tool_choice"] == "auto"
        assert len(model.calls[0]["tools"]) == 1


async def _no_tools():
    return []


class TestRetrieval:
    async def test_documents_come_back_as_text(self, monkeypatch):
        monkeypatch.setattr(documents_node, "get_store", lambda: object())
        monkeypatch.setattr(
            documents_node,
            "vector_search",
            lambda store, question, limit: [{"answer": "  a doc  "}, {"answer": ""}],
        )
        update = await documents_node.retrieve_documents({"question": QUESTION})
        assert update == {"documents": ["a doc"]}, "blank payloads are dropped"

    async def test_a_failing_store_does_not_fail_the_answer(self, monkeypatch):
        monkeypatch.setattr(documents_node, "get_store", lambda: object())

        def explode(*args, **kwargs):
            raise RuntimeError("qdrant is down")

        monkeypatch.setattr(documents_node, "vector_search", explode)
        assert await documents_node.retrieve_documents({"question": QUESTION}) == {"documents": []}

    async def test_instructions_use_the_configured_payload_field(self, monkeypatch, config):
        monkeypatch.setattr(instructions_node, "get_instruction_store", lambda: object())
        monkeypatch.setattr(
            instructions_node,
            "vector_search",
            lambda store, question, limit: [{"instruction": "Always name the dose form."}],
        )
        update = await instructions_node.retrieve_instructions({"question": QUESTION})
        assert update == {"instructions": ["Always name the dose form."]}

    async def test_a_wrong_payload_field_yields_nothing(self, monkeypatch):
        monkeypatch.setattr(instructions_node, "get_instruction_store", lambda: object())
        monkeypatch.setattr(
            instructions_node, "vector_search", lambda *a, **k: [{"text": "wrong key"}]
        )
        assert await instructions_node.retrieve_instructions({"question": QUESTION}) == {
            "instructions": []
        }

    async def test_history_is_returned_oldest_first(self, monkeypatch):
        class Row:
            def __init__(self, content):
                self.content = content

        monkeypatch.setattr(history_node, "async_session_scope", _fake_session_scope)

        async def rows(session, session_uid, *, limit):
            return [Row("older"), Row("newer")]

        monkeypatch.setattr(history_node, "list_recent_user_messages", rows)
        update = await history_node.retrieve_history({"question": QUESTION, "session_uid": SESSION})
        assert update == {"history": ["older", "newer"]}

    async def test_a_failing_database_does_not_fail_the_answer(self, monkeypatch):
        monkeypatch.setattr(history_node, "async_session_scope", _fake_session_scope)

        async def explode(*args, **kwargs):
            raise RuntimeError("postgres is down")

        monkeypatch.setattr(history_node, "list_recent_user_messages", explode)
        update = await history_node.retrieve_history({"question": QUESTION, "session_uid": SESSION})
        assert update == {"history": []}


def _fake_session_scope():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def scope():
        yield object()

    return scope()
