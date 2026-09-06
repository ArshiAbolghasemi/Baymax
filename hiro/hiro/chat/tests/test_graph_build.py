"""The compiled workflow: its shape, and how a run streams out of it."""

import uuid

import pytest

from hiro.chat.agent import graph
from hiro.chat.agent.events import TextDelta, ToolCall, ToolResult

SESSION = uuid.uuid4()


class FakeTool:
    """The smallest thing ToolNode accepts."""

    name = "search_drug_label"
    description = "look up a label"
    args_schema = None

    def __init__(self):
        self.is_single_input = True


@pytest.fixture
def rebuilt_graph(monkeypatch):
    """The graph is compiled once per process; tests must not inherit one."""
    monkeypatch.setattr(graph, "_graph", None)
    yield
    monkeypatch.setattr(graph, "_graph", None)


class TestCompilation:
    async def test_the_graph_is_built_once(self, rebuilt_graph, monkeypatch):
        calls = 0

        async def tools():
            nonlocal calls
            calls += 1
            return []

        monkeypatch.setattr(graph, "get_mcp_tools", tools)
        first = await graph.get_graph()
        second = await graph.get_graph()

        assert first is second
        assert calls == 1, "tool discovery is not repeated per question"

    async def test_every_node_is_wired(self, rebuilt_graph, monkeypatch):
        async def tools():
            return []

        monkeypatch.setattr(graph, "get_mcp_tools", tools)
        compiled = await graph.get_graph()
        nodes = set((await compiled.aget_graph()).nodes)

        assert {"guardrail", graph.ANSWER_NODE, graph.BLOCKED_NODE, graph.TOOLS_NODE} <= nodes
        assert set(graph.RETRIEVAL_NODES) <= nodes


class TestStreamAnswer:
    async def test_tokens_from_other_nodes_never_reach_the_client(self, rebuilt_graph, monkeypatch):
        """The guardrail's single character must not be streamed as an answer."""
        from langchain_core.messages import AIMessage

        async def astream(state, stream_mode):
            yield "messages", (AIMessage(content="1"), {"langgraph_node": "guardrail"})
            yield "messages", (AIMessage(content="hello"), {"langgraph_node": graph.ANSWER_NODE})

        monkeypatch.setattr(graph, "get_graph", _fake_graph(astream))
        events = [e async for e in graph.stream_answer("q", SESSION)]
        assert events == [TextDelta("hello")]

    async def test_a_refusal_is_streamed_from_the_blocked_branch(self, rebuilt_graph, monkeypatch):
        """That branch calls no model, so it emits no tokens of its own."""

        async def astream(state, stream_mode):
            yield "updates", {graph.BLOCKED_NODE: {"answer": "I can not process this request."}}

        monkeypatch.setattr(graph, "get_graph", _fake_graph(astream))
        events = [e async for e in graph.stream_answer("q", SESSION)]
        assert events == [TextDelta("I can not process this request.")]

    async def test_tool_calls_and_results_are_emitted_in_order(self, rebuilt_graph, monkeypatch):
        from langchain_core.messages import AIMessage, ToolMessage

        reply = AIMessage(
            content="", tool_calls=[{"name": "search_drug_label", "args": {"d": "x"}, "id": "c1"}]
        )

        async def astream(state, stream_mode):
            yield "updates", {graph.ANSWER_NODE: {"messages": [reply]}}
            yield (
                "updates",
                {
                    graph.TOOLS_NODE: {
                        "messages": [
                            ToolMessage(content="{}", name="search_drug_label", tool_call_id="c1")
                        ]
                    }
                },
            )
            yield "messages", (AIMessage(content="done"), {"langgraph_node": graph.ANSWER_NODE})

        monkeypatch.setattr(graph, "get_graph", _fake_graph(astream))
        events = [e async for e in graph.stream_answer("q", SESSION)]

        assert events == [
            ToolCall(id="c1", name="search_drug_label", arguments={"d": "x"}),
            ToolResult(tool_call_id="c1", name="search_drug_label", content="{}"),
            TextDelta("done"),
        ]

    async def test_a_failing_run_is_not_swallowed(self, rebuilt_graph, monkeypatch):
        async def astream(state, stream_mode):
            raise RuntimeError("the graph died")
            yield  # pragma: no cover

        monkeypatch.setattr(graph, "get_graph", _fake_graph(astream))
        with pytest.raises(RuntimeError):
            async for _ in graph.stream_answer("q", SESSION):
                pass


def _fake_graph(astream):
    async def get_graph():
        return type("G", (), {"astream": staticmethod(astream)})()

    return get_graph
