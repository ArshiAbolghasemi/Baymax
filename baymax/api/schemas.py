"""Schemas for the API's own endpoints."""

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok"}]})

    status: str
