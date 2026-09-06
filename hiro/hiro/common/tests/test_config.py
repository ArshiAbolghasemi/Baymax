"""Configuration: defaults, overrides, and the composition of the whole."""

import uuid

from hiro.config import get_config


def test_composes_every_package(config):
    assert config.chat.agent_model_name == "baymax"
    assert config.database.url.startswith("postgresql+psycopg://")
    assert config.embedding.dimensions == 4
    assert config.qdrant.url == "http://qdrant.invalid:6333"


def test_bare_postgres_scheme_is_upgraded(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    get_config.cache_clear()
    assert get_config().database.url == "postgresql+psycopg://u:p@host:5432/db"


class TestChat:
    def test_prompt_identifiers_have_defaults(self, config):
        assert config.chat.prompt_answer == "hiro-answer"
        assert config.chat.prompt_guardrail == "hiro-guardrail"
        assert config.chat.prompt_blocked == "hiro-blocked"
        assert config.chat.prompt_no_documents == "hiro-no-documents"

    def test_prompt_identifier_is_overridable(self, monkeypatch):
        monkeypatch.setenv("CHAT_PROMPT_ANSWER", "house-answer")
        get_config.cache_clear()
        assert get_config().chat.prompt_answer == "house-answer"

    def test_session_namespace_is_a_uuid(self, config):
        assert isinstance(config.chat.session_namespace, uuid.UUID)

    def test_retrieval_limits(self, config):
        assert config.chat.retrieval_top_k == 5
        assert config.chat.instruction_top_k == 5
        assert config.chat.instruction_collection == "hiro_instructions"


class TestPhoenix:
    def test_collector_defaults_to_the_prompt_host(self, config):
        assert config.phoenix.collector_endpoint == "http://phoenix.invalid:6006/v1/traces"

    def test_collector_is_overridable(self, monkeypatch):
        monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://otel.invalid:4317")
        get_config.cache_clear()
        assert get_config().phoenix.collector_endpoint == "http://otel.invalid:4317"

    def test_api_key_is_empty_by_default(self, config):
        """A secret is the one thing with no default."""
        assert config.phoenix.api_key == ""


class TestMcp:
    def test_defaults_to_the_dobby_container(self, config):
        assert config.mcp.url == "http://mcp.invalid:8090/mcp"
        assert config.mcp.timeout == 30
        assert config.mcp.read_timeout == 60
