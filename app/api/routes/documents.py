"""Document ingestion and lifecycle endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status

from app.api.dependencies import get_document_processor, get_document_service
from app.schemas.document import DocumentStatusResponse, DocumentUploadResponse
from app.services.document_ingestion_service import DocumentProcessor
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"description": "The uploaded file is empty or invalid."},
        415: {"description": "The uploaded document type is not supported."},
    },
)
def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="A shipping PDF or image")],
    service: Annotated[DocumentService, Depends(get_document_service)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
) -> DocumentUploadResponse:
    """Persist a shipping document and dispatch its ingestion pipeline."""
    response = service.create_document(
        filename=file.filename or "",
        content_type=file.content_type,
        stream=file.file,
    )
    background_tasks.add_task(processor.process_document, response.document_id)
    return response


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    responses={404: {"description": "The document does not exist."}},
)
def get_document_status(
    document_id: UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentStatusResponse:
    """Get the current processing status for a document."""
    return service.get_document_status(document_id)