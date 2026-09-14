"""Operational health endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_answer_generator, get_app_settings
from app.core.config import Settings
from app.schemas.common import HealthResponse, LlmStatusResponse
from app.services.answer_generation_service import AnswerGenerator

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> HealthResponse:
    """Report whether the API process is responsive."""
    return HealthResponse(service=settings.app_name, version=settings.app_version)


@router.get("/llm/status", response_model=LlmStatusResponse)
async def llm_status(
    settings: Annotated[Settings, Depends(get_app_settings)],
    generator: Annotated[AnswerGenerator | None, Depends(get_answer_generator)],
) -> LlmStatusResponse:
    """Check whether Ollama is active and return the default model configuration."""
    available = generator.is_available() if generator is not None else False
    return LlmStatusResponse(
        ollama_available=available,
        default_model=settings.ollama_model,
        mode=settings.llm_mode,
    )