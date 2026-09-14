"""Operational health endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings
from app.core.config import Settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthResponse:
    """Report whether the API process is responsive."""
    return HealthResponse(service=settings.app_name, version=settings.app_version)