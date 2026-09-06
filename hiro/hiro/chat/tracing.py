"""One decorator for everything hiro traces by hand.

The LangChain instrumentation already produces a span per graph node, an LLM
span carrying the exact messages sent and the reply, and a tool span per MCP
call. What it cannot know is added by decorating the functions that do know:

* **Whose conversation this is.** ``conversation`` sets ``session.id`` and
  ``user.id`` as OpenInference context, so *every* span of the turn carries
  them — which is what makes "the tools I chose in this session" a question
  Phoenix can answer.
* **What went in and what came out.** ``input`` reads the call's arguments and
  ``output`` reads its result, so the turn shows the question and the reply,
  retrieval shows the documents it injected, and a prompt fetch shows the
  wording it handed the model.

The decorated function keeps its own shape: a node still reads state and
returns state, and nothing in it mentions a span. Async functions and async
generators are both supported — for a generator, ``output`` is handed
everything it yielded, once it is done.

    @trace("retrieve history", kind="retriever",
           input=lambda state: state["question"],
           output=lambda update: update["history"])
    async def retrieve_history(state: AgentState) -> AgentState: ...
"""

import inspect
import uuid
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from functools import wraps
from typing import Any

from openinference.instrumentation import using_session, using_user
from openinference.semconv.trace import DocumentAttributes, SpanAttributes
from opentelemetry.trace import Span, get_current_span

from hiro.common.logging import get_logger
from hiro.common.tracing import get_tracer

logger = get_logger(__name__)

#: ``(session_uid, user_uid)``, as read from a traced call's arguments.
Conversation = tuple[uuid.UUID, uuid.UUID]


def trace(
    name: str | Callable[..., str] | None = None,
    *,
    kind: str = "chain",
    conversation: Callable[..., Conversation] | None = None,
    input: Callable[..., Any] | None = None,
    output: Callable[[Any], Any] | None = None,
    attributes: Callable[..., dict[str, Any]] | None = None,
    records: Callable[[Any], dict[str, Any]] | None = None,
    propagate: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record one span around a function.

    Every hook is optional and reads only what the call already has:

    ``name``
        The span name, or a callable over the arguments when it depends on them
        (``lambda identifier, **_: f"prompt {identifier}"``). Defaults to the
        function's own name.
    ``kind``
        OpenInference span kind: ``agent``, ``retriever``, ``chain``, ``tool``.
        It is a parameter of the tracer rather than an attribute, which is how
        Phoenix decides what the span *is*.
    ``conversation``
        Returns the session and user to bind for the whole call, and everything
        it calls.
    ``input`` / ``output``
        Read from the arguments and the result. A string is recorded as the
        span's value; a sequence of strings as retrieved documents.
    ``attributes``
        Anything else worth keeping from the arguments, as a plain dict.
    ``propagate``
        Stamp the same input, output and attributes onto the enclosing span as
        well. Phoenix's session list shows each trace by its *root* span, and
        the root here is the HTTP span, which cannot know the question or the
        reply — without this, a session reads as a column of blanks.
    ``records``
        The same, but read from the result — which is where a list of the tools
        the model selected lives, since that is only known once the step has
        run. Sequences are kept as sequences, so the value stays filterable in
        Phoenix rather than becoming prose.
    """

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or function.__name__

        def open_span(
            stack: ExitStack, args: tuple[Any, ...], kwargs: dict[str, Any]
        ) -> tuple[Span, Span | None]:
            # Captured before ours starts, so it is the enclosing span.
            enclosing = get_current_span() if propagate else None

            if conversation is not None:
                session_uid, user_uid = conversation(*args, **kwargs)
                stack.enter_context(using_session(str(session_uid)))
                stack.enter_context(using_user(str(user_uid)))
                extra: dict[str, Any] = {
                    SpanAttributes.SESSION_ID: str(session_uid),
                    SpanAttributes.USER_ID: str(user_uid),
                }
            else:
                extra = {}

            if input is not None:
                extra[SpanAttributes.INPUT_VALUE] = str(input(*args, **kwargs))
            if attributes is not None:
                extra.update(attributes(*args, **kwargs))

            if enclosing is not None and enclosing.is_recording():
                _stamp(enclosing, extra)

            resolved = span_name(*args, **kwargs) if callable(span_name) else span_name
            span = stack.enter_context(
                get_tracer().start_as_current_span(
                    resolved,
                    openinference_span_kind=kind,
                    attributes=extra,
                )
            )
            return span, enclosing

        if inspect.isasyncgenfunction(function):

            @wraps(function)
            async def traced_stream(*args: Any, **kwargs: Any) -> Any:
                produced: list[Any] = []
                with ExitStack() as stack:
                    span, enclosing = open_span(stack, args, kwargs)
                    async for item in function(*args, **kwargs):
                        produced.append(item)
                        yield item
                    _record(span, output, records, produced, enclosing)

            return traced_stream

        @wraps(function)
        async def traced(*args: Any, **kwargs: Any) -> Any:
            with ExitStack() as stack:
                span, enclosing = open_span(stack, args, kwargs)
                result = await function(*args, **kwargs)
                _record(span, output, records, result, enclosing)
                return result

        return traced

    return decorate


def _record(
    span: Span,
    output: Callable[[Any], Any] | None,
    records: Callable[[Any], dict[str, Any]] | None,
    result: Any,
    enclosing: Span | None = None,
) -> None:
    """Put the result on the span: text as a value, a list as documents."""
    # A trace must never be the reason an answer fails, so every hook that
    # reads a result is allowed to be wrong about its shape.
    if records is not None:
        try:
            recorded = {k: v for k, v in records(result).items() if v is not None}
            _stamp(span, recorded)
            if enclosing is not None and enclosing.is_recording():
                _stamp(enclosing, recorded)
        except Exception:
            logger.exception("tracing could not record attributes of a span")

    if output is None:
        return

    try:
        value = output(result)
    except Exception:
        logger.exception("tracing could not read the result of a span")
        return

    if value is None:
        return
    if isinstance(value, str):
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, value)
        if enclosing is not None and enclosing.is_recording():
            enclosing.set_attribute(SpanAttributes.OUTPUT_VALUE, value)
        return
    if isinstance(value, Sequence):
        for index, document in enumerate(value):
            span.set_attribute(
                f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.{index}"
                f".{DocumentAttributes.DOCUMENT_CONTENT}",
                str(document),
            )
        span.set_attribute("hiro.retrieved", len(value))


def _stamp(span: Span, attributes: dict[str, Any]) -> None:
    """Set many attributes at once, skipping the ones with nothing to say."""
    for key, value in attributes.items():
        span.set_attribute(key, value)
