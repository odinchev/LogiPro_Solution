"""Schemas shared by operational endpoints."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class HealthResponse(BaseModel):
    """Health-check response."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    timestamp: datetime = Field(default_factory=utc_now)


class ServiceInfoResponse(BaseModel):
    """Basic service-discovery information."""

    name: str
    version: str
    environment: str
    docs_url: str


class LlmStatusResponse(BaseModel):
    """Runtime availability and configuration for the local LLM."""

    ollama_available: bool
    default_model: str
    mode: str