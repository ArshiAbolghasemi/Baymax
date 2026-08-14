"""HTTP API configuration."""

from dynaconf import Dynaconf

from common.env import dynaconf_kwargs

DEFAULT_DESCRIPTION = """
Ingestion API for the Baymax medical Assistan.
""".strip()


class ApiConfig(Dynaconf):
    """FastAPI application settings."""

    def __init__(self) -> None:
        super().__init__(**dynaconf_kwargs())

    @property
    def title(self) -> str:
        return str(self.get("API_TITLE", "Baymax API"))

    @property
    def version(self) -> str:
        return str(self.get("API_VERSION", "0.1.0"))

    @property
    def description(self) -> str:
        return str(self.get("API_DESCRIPTION", DEFAULT_DESCRIPTION))

    @property
    def root_path(self) -> str:
        """Set when served behind a path-rewriting proxy."""
        return str(self.get("API_ROOT_PATH", ""))

    @property
    def docs_enabled(self) -> bool:
        """Serve Swagger UI, ReDoc and the OpenAPI schema.

        Worth turning off in production: the schema documents every field and
        error of an internal service, and there is no auth in front of it.
        """
        return bool(self.get("API_DOCS_ENABLED", True))

    @property
    def docs_url(self) -> str:
        """Swagger UI path."""
        return str(self.get("API_DOCS_URL", "/docs"))

    @property
    def redoc_url(self) -> str:
        return str(self.get("API_REDOC_URL", "/redoc"))

    @property
    def openapi_url(self) -> str:
        return str(self.get("API_OPENAPI_URL", "/openapi.json"))
