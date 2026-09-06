"""The application itself: what it exposes, and what it refuses to expose."""

import pytest
from fastapi.testclient import TestClient

from hiro.api.app import create_app
from hiro.api.middleware import CORRELATION_HEADER
from hiro.config import get_config


class FakeStore:
    """Qdrant, reduced to the one call start-up makes."""

    collection = "test"

    def ensure_collection(self) -> None:
        self.ensured = True


async def _noop(*args, **kwargs):
    return None


def stub_startup(monkeypatch):
    """Start-up talks to Qdrant, Phoenix and Postgres. None of them are here."""
    monkeypatch.setattr("hiro.api.app.configure_tracing", lambda: None)
    monkeypatch.setattr("hiro.api.app.shutdown_tracing", lambda: None)
    monkeypatch.setattr("hiro.api.app.get_store", FakeStore)
    monkeypatch.setattr("hiro.api.app.dispose_async_engine", _noop)


@pytest.fixture
def app(monkeypatch):
    stub_startup(monkeypatch)
    return create_app()


def test_health_is_public(app):
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_every_route_is_mounted(app):
    """Read from the schema: included routers are not flattened into app.routes."""
    paths = set(app.openapi()["paths"])
    assert paths == {
        "/health",
        "/v1/models",
        "/v1/sessions",
        "/v1/chat/completions",
        "/v1/knowledge-base/qa",
        "/v1/knowledge-base/qa/{answer_uid}",
    }


def test_a_request_id_is_echoed_back(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={CORRELATION_HEADER: "abc-123"})
        assert response.headers[CORRELATION_HEADER] == "abc-123"


def test_a_request_without_an_id_still_gets_one(app):
    with TestClient(app) as client:
        assert client.get("/health").headers[CORRELATION_HEADER]


def test_docs_can_be_switched_off(monkeypatch):
    """The schema documents every field and error of an internal service."""
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    get_config.cache_clear()
    stub_startup(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
