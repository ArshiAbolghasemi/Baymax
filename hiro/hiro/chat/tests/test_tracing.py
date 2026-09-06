"""The trace decorator itself: what it records, and what it refuses to break."""

import uuid

import pytest

from hiro.chat.tracing import trace


class TestSpanShape:
    async def test_the_function_keeps_its_own_signature_and_result(self, spans):
        @trace("named")
        async def node(state):
            """A doc that must survive decoration."""
            return {"documents": ["one"]}

        assert await node({"question": "q"}) == {"documents": ["one"]}
        assert node.__name__ == "node"
        assert node.__doc__.startswith("A doc")

    async def test_the_span_is_named_after_the_function_by_default(self, spans):
        @trace()
        async def retrieve_history(state):
            return {}

        await retrieve_history({})
        assert "retrieve_history" in spans()

    async def test_the_name_may_be_read_from_the_arguments(self, spans):
        @trace(lambda identifier, **_: f"prompt {identifier}")
        async def fetch(identifier):
            return []

        await fetch("hiro-answer")
        assert "prompt hiro-answer" in spans()

    @pytest.mark.parametrize(
        ("kind", "expected"), [("agent", "AGENT"), ("retriever", "RETRIEVER"), ("chain", "CHAIN")]
    )
    async def test_the_kind_reaches_phoenix(self, spans, kind, expected):
        @trace("step", kind=kind)
        async def node(state):
            return {}

        await node({})
        assert spans()["step"].attributes["openinference.span.kind"] == expected


class TestRecording:
    async def test_input_and_output_are_read_from_the_call(self, spans):
        @trace(
            "step", input=lambda state: state["question"], output=lambda update: update["answer"]
        )
        async def node(state):
            return {"answer": "42"}

        await node({"question": "the question"})
        attributes = spans()["step"].attributes
        assert attributes["input.value"] == "the question"
        assert attributes["output.value"] == "42"

    async def test_a_list_output_is_recorded_as_documents(self, spans):
        @trace("step", kind="retriever", output=lambda update: update["documents"])
        async def node(state):
            return {"documents": ["first", "second"]}

        await node({})
        attributes = spans()["step"].attributes
        assert attributes["hiro.retrieved"] == 2
        assert attributes["retrieval.documents.1.document.content"] == "second"

    async def test_attributes_come_from_the_arguments(self, spans):
        @trace("step", attributes=lambda state: {"hiro.collection": state["collection"]})
        async def node(state):
            return {}

        await node({"collection": "hiro_instructions"})
        assert spans()["step"].attributes["hiro.collection"] == "hiro_instructions"

    async def test_records_come_from_the_result(self, spans):
        """A tool list only exists once the step has run."""

        @trace("step", records=lambda update: {"llm.tools.selected": update["tools"]})
        async def node(state):
            return {"tools": ["search_drug_label", "search_genetics"]}

        await node({})
        assert spans()["step"].attributes["llm.tools.selected"] == (
            "search_drug_label",
            "search_genetics",
        )

    async def test_the_conversation_tags_the_span_and_its_children(self, spans):
        session, user = uuid.uuid4(), uuid.uuid4()

        @trace("child")
        async def child():
            return {}

        @trace("parent", conversation=lambda: (session, user))
        async def parent():
            return await child()

        await parent()
        finished = spans()
        assert finished["parent"].attributes["session.id"] == str(session)
        assert finished["child"].attributes["session.id"] == str(session), "inherited by context"
        assert finished["child"].attributes["user.id"] == str(user)


class TestStreams:
    async def test_events_pass_through_and_the_result_is_the_whole_stream(self, spans):
        @trace("stream", output=lambda items: "".join(items))
        async def produce():
            yield "a"
            yield "b"

        assert [item async for item in produce()] == ["a", "b"]
        assert spans()["stream"].attributes["output.value"] == "ab"

    async def test_a_failing_stream_still_closes_its_span(self, spans):
        @trace("stream")
        async def produce():
            yield "a"
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            async for _ in produce():
                pass
        assert "stream" in spans(), "the span is ended, not leaked"


class TestPropagation:
    async def test_the_enclosing_span_is_stamped_too(self, spans):
        """Phoenix's session list reads the root span, which cannot know these."""
        session, user = uuid.uuid4(), uuid.uuid4()

        @trace(
            "turn",
            kind="agent",
            conversation=lambda: (session, user),
            input=lambda: "the question",
            output=lambda items: "the answer",
            records=lambda items: {"llm.tools.selected": ["search_genetics"]},
            propagate=True,
        )
        async def turn():
            return []

        from hiro.chat.tracing import get_tracer

        with get_tracer().start_as_current_span(
            "chat.completions", openinference_span_kind="chain"
        ):
            await turn()

        root = spans()["chat.completions"].attributes
        assert root["input.value"] == "the question"
        assert root["output.value"] == "the answer"
        assert root["session.id"] == str(session)
        assert root["llm.tools.selected"] == ("search_genetics",)

    async def test_without_propagation_the_root_stays_bare(self, spans):
        @trace("turn", input=lambda: "q", output=lambda r: "a")
        async def turn():
            return []

        from hiro.chat.tracing import get_tracer

        with get_tracer().start_as_current_span("root", openinference_span_kind="chain"):
            await turn()

        assert "input.value" not in spans()["root"].attributes


class TestFailureIsolation:
    async def test_a_broken_output_hook_does_not_break_the_call(self, spans):
        @trace("step", output=lambda update: update["missing"])
        async def node(state):
            return {"answer": "still returned"}

        assert await node({}) == {"answer": "still returned"}

    async def test_a_broken_records_hook_does_not_break_the_call(self, spans):
        @trace("step", records=lambda update: 1 / 0)
        async def node(state):
            return {"answer": "still returned"}

        assert await node({}) == {"answer": "still returned"}
