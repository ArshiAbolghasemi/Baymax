"""Test-wide setup: use test configuration and export no real traces."""

import os
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

os.environ["DOTENV_PATH_FOR_DYNACONF"] = str(Path(__file__).with_name(".env.test"))


@pytest.fixture(autouse=True)
def config():
    """Fresh application configuration per test.

    ``get_config`` is cached for the life of a process, so the cache is cleared
    on the way in *and* out: a test that overrides a variable must not leak that
    override into the next one.
    """
    from hiro.config import get_config

    get_config.cache_clear()
    yield get_config()
    get_config.cache_clear()


@pytest.fixture(autouse=True)
def spans(monkeypatch):
    """Collect spans in memory instead of shipping them to Phoenix.

    Autouse: the traced code paths run in most tests, and a tracer configured
    from the environment above would spend the suite retrying an export to a
    host that does not exist. Returns a callable that reads the spans finished
    so far, by name.
    """
    from openinference.instrumentation import OITracer, TraceConfig

    import hiro.chat.tracing as tracing

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = OITracer(provider.get_tracer("tests"), config=TraceConfig())
    monkeypatch.setattr(tracing, "get_tracer", lambda: tracer)

    def finished() -> dict:
        return {span.name: span for span in exporter.get_finished_spans()}

    return finished
