"""FastAPI application factory.

Run with::

    uv run uvicorn hiro.api.app:app --reload

Swagger UI is then at http://localhost:8000/docs and ReDoc at /redoc.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hiro.api.middleware import CorrelationIdMiddleware
from hiro.api.schemas import HealthResponse
from hiro.chat.router import router as chat_router
from hiro.common.logging import configure_logging, get_logger
from hiro.config import get_config
from hiro.db.session import dispose_async_engine
from hiro.knowledge_base.router import router as knowledge_base_router
from hiro.knowledge_base.store import get_store

logger = get_logger(__name__)

# Section blurbs shown above each group of endpoints in Swagger UI.
OPENAPI_TAGS = [
    {
        "name": "knowledge-base: qa",
        "description": (
            "Question/answer entries: store answers with the questions they "
            "satisfy, and track how far vector indexing has progressed. Other "
            "source types (documents, guidelines) will appear as sibling tags."
        ),
    },
    {
        "name": "chat",
        "description": (
            "OpenAI-compatible agent model discovery and chat completions. "
            "Responses are available as JSON or server-sent event streams."
        ),
    },
    {
        "name": "ops",
        "description": "Probes for orchestrators and load balancers.",
    },
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    config = get_config().api
    logger.info("starting %s %s", config.title, config.version)

    # The worker also calls this, but doing it here means the collection exists
    # before the first request rather than after the first task runs.
    store = get_store()
    store.ensure_collection()
    logger.info("qdrant collection %s ready", store.collection)

    if config.docs_enabled:
        logger.info("api docs at %s and %s", config.docs_url, config.redoc_url)
    else:
        logger.info("api docs disabled")

    yield

    await dispose_async_engine()
    logger.info("shutting down")


def create_app() -> FastAPI:
    configure_logging()
    config = get_config().api

    app = FastAPI(
        title=config.title,
        version=config.version,
        description=config.description,
        root_path=config.root_path,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        # Passing None for these disables the routes entirely, which is what
        # API_DOCS_ENABLED=false is for.
        docs_url=config.docs_url if config.docs_enabled else None,
        redoc_url=config.redoc_url if config.docs_enabled else None,
        openapi_url=config.openapi_url if config.docs_enabled else None,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(knowledge_base_router)
    app.include_router(chat_router)

    @app.get(
        "/health",
        tags=["ops"],
        summary="Liveness probe",
        description="Returns 200 as long as the process is serving requests. "
        "Does not check Postgres, Redis or Qdrant.",
        response_model=HealthResponse,
    )
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
