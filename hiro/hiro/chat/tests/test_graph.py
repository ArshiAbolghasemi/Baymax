"""The workflow's own decisions: what it streams, and where it goes next."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from hiro.chat.agent import graph
from hiro.chat.agent.events import ToolCall, ToolResult


class TestAssistantText:
    def test_plain_assistant_text(self):
        assert graph.assistant_text(AIMessage(content="hello")) == "hello"

    def test_non_assistant_messages_are_dropped(self):
        """The answer node returns its whole prompt into state on the first pass."""
        assert graph.assistant_text(HumanMessage(content="the question")) == ""

    def test_reasoning_blocks_never_reach_the_client(self):
        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "private reasoning"},
                {"type": "text", "text": "the answer"},
            ]
        )
        assert graph.assistant_text(message) == "the answer"

    def test_bare_strings_inside_a_block_list_are_kept(self):
        assert graph.assistant_text(AIMessage(content=["a", "b"])) == "ab"

    def test_unusable_content_is_empty(self):
        """Content is str-or-list by contract; anything else yields nothing."""

        class Odd(AIMessage):
            pass

        message = Odd(content="")
        object.__setattr__(message, "content", {"unexpected": True})
        assert graph.assistant_text(message) == ""


class TestRouting:
    def test_a_blocked_question_goes_to_the_refusal(self):
        assert graph.route_after_guardrail({"allowed": False}) == graph.BLOCKED_NODE

    def test_an_allowed_question_fans_out_to_every_retrieval_step(self):
        assert graph.route_after_guardrail({"allowed": True}) == graph.RETRIEVAL_NODES

    def test_a_missing_verdict_is_treated_as_blocked(self):
        assert graph.route_after_guardrail({}) == graph.BLOCKED_NODE

    def test_the_loop_continues_only_when_a_tool_was_requested(self):
        wants_tool = AIMessage(
            content="",
            tool_calls=[{"name": "search_drug_label", "args": {}, "id": "call_1"}],
        )
        assert graph.route_after_answer({"messages": [wants_tool]}) == graph.TOOLS_NODE

    def test_a_plain_answer_ends_the_run(self):
        assert graph.route_after_answer({"messages": [AIMessage(content="done")]}) == END

    def test_no_messages_ends_the_run(self):
        assert graph.route_after_answer({}) == END


class TestEventExtraction:
    def test_tool_calls_are_read_from_the_last_message(self):
        update = {
            "messages": [
                AIMessage(content="ignored"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_drug_label", "args": {"drug_name": "x"}, "id": "c1"}
                    ],
                ),
            ]
        }
        assert graph._tool_calls(update) == [
            ToolCall(id="c1", name="search_drug_label", arguments={"drug_name": "x"})
        ]

    def test_no_tool_calls_is_no_events(self):
        assert graph._tool_calls({"messages": [AIMessage(content="hi")]}) == []
        assert graph._tool_calls({}) == []

    def test_every_tool_message_becomes_a_result(self):
        update = {
            "messages": [
                ToolMessage(content="{}", name="search_genetics", tool_call_id="c1"),
                ToolMessage(content="[]", name="search_health_info", tool_call_id="c2"),
            ]
        }
        assert graph._tool_results(update) == [
            ToolResult(tool_call_id="c1", name="search_genetics", content="{}"),
            ToolResult(tool_call_id="c2", name="search_health_info", content="[]"),
        ]
