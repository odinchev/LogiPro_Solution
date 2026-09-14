"""Document lifecycle API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentUploadResponse(BaseModel):
    """Response returned after a document is accepted for processing."""

    document_id: UUID
    filename: str
    content_type: str | None = None
    status: DocumentStatus
    created_at: datetime


class DocumentStatusResponse(BaseModel):
    """Current processing state and metadata for a document."""

    document_id: UUID
    filename: str
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None