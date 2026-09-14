"""Persistence adapters for application data."""

from app.repositories.document_repository import DocumentRepository
from app.repositories.sqlite_document_repository import SQLiteDocumentRepository

__all__ = ["DocumentRepository", "SQLiteDocumentRepository"]