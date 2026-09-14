"""FastAPI dependency providers."""

from fastapi import Request

from app.core.config import Settings
from app.services.document_ingestion_service import DocumentProcessor
from app.services.document_service import DocumentService
from app.services.rag_service import RagService


def get_app_settings(request: Request) -> Settings:
    """Provide the settings used to construct this application instance."""
    return request.app.state.settings


def get_document_service(request: Request) -> DocumentService:
    """Provide the document application service."""
    return request.app.state.document_service


def get_document_processor(request: Request) -> DocumentProcessor:
    """Provide the background document ingestion service."""
    return request.app.state.document_processor


def get_rag_service(request: Request) -> RagService:
    """Provide the retrieval-augmented generation service."""
    return request.app.state.rag_service