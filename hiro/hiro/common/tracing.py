"""Phoenix tracing shared by the API and its instrumented LangGraph calls."""

from functools import lru_cache

from opentelemetry.trace import Tracer
from phoenix.otel import TracerProvider, register

from hiro.config import get_config

_provider: TracerProvider | None = None


def configure_tracing() -> None:
    """Connect OpenTelemetry to Phoenix and instrument installed LangChain hooks."""
    global _provider
    if _provider is not None:
        return

    config = get_config().phoenix
    _provider = register(
        endpoint=config.collector_endpoint,
        project_name=config.project_name,
        protocol="http/protobuf",
        batch=True,
        auto_instrument=True,
        api_key=config.api_key or None,
        verbose=False,
    )


@lru_cache(maxsize=1)
def get_tracer() -> Tracer:
    configure_tracing()
    assert _provider is not None
    return _provider.get_tracer("hiro.chat")


def shutdown_tracing() -> None:
    """Flush queued spans before the process exits."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
        get_tracer.cache_clear()
