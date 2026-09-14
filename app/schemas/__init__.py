"""Pydantic API contracts for the Document Intelligence Service."""

from app.schemas.common import HealthResponse, LlmStatusResponse, ServiceInfoResponse
from app.schemas.document import (
    DocumentStatus,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.schemas.query import Citation, QueryRequest, QueryResponse

__all__ = [
    "Citation",
    "DocumentStatus",
    "DocumentStatusResponse",
    "DocumentUploadResponse",
    "HealthResponse",
    "LlmStatusResponse",
    "QueryRequest",
    "QueryResponse",
    "ServiceInfoResponse",
]