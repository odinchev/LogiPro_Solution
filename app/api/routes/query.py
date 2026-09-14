"""Natural-language document query endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_rag_service
from app.schemas.query import QueryRequest, QueryResponse
from app.services.rag_service import RagService

router = APIRouter(prefix="/documents", tags=["Queries"])


@router.post(
    "/{document_id}/query",
    response_model=QueryResponse,
    responses={
        404: {"description": "The document does not exist."},
        409: {"description": "The document is not ready for querying."},
        503: {"description": "Context or the required LLM is unavailable."},
    },
)
def query_document(
    document_id: UUID,
    request: QueryRequest,
    service: Annotated[RagService, Depends(get_rag_service)],
) -> QueryResponse:
    """Ask a question about one processed document."""
    return service.query_document(document_id=document_id, request=request)