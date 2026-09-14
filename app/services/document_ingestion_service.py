"""Background orchestration for document extraction and vector ingestion."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.models.document import DocumentStatus
from app.models.ingestion import ExtractedPage, TextChunk
from app.repositories.document_repository import DocumentRepository
from app.services.embedding_service import EmbeddingService
from app.services.text_chunking_service import TextChunkingService
from app.services.vector_store_service import VectorStore

logger = logging.getLogger(__name__)

_MAX_ERROR_MESSAGE_LENGTH = 2_000


class DocumentProcessor(Protocol):
    """A background processor that ingests one persisted document."""

    def process_document(self, document_id: UUID) -> None:
        """Process one document and persist its terminal status."""
        ...


class PageTextExtractor(Protocol):
    """Extract page-aware text from a document file."""

    def extract(self, document_path: Path) -> list[ExtractedPage]:
        """Return extracted pages in source order."""
        ...


class DocumentIngestionService:
    """Run extraction, chunking, embedding, and vector persistence."""

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        text_extractor: PageTextExtractor,
        text_chunker: TextChunkingService,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
    ) -> None:
        self._repository = repository
        self._text_extractor = text_extractor
        self._text_chunker = text_chunker
        self._embedding_service = embedding_service
        self._vector_store = vector_store

    def process_document(self, document_id: UUID) -> None:
        """Process a document and record ``READY`` or ``FAILED`` in SQLite."""
        try:
            document = self._repository.get_by_id(document_id)
        except Exception as exc:
            logger.exception("Could not load document %s for ingestion", document_id)
            self._mark_failed(document_id, exc)
            return

        if document is None:
            logger.error("Cannot process missing document %s", document_id)
            return
        if document.status is not DocumentStatus.PROCESSING:
            logger.info(
                "Skipping document %s because its status is %s",
                document_id,
                document.status.value,
            )
            return

        try:
            pages = self._text_extractor.extract(document.path)
            chunks = self._text_chunker.chunk_pages(
                document_id=document.id,
                filename=document.filename,
                pages=pages,
            )
            if not chunks:
                raise ValueError("No usable text could be extracted from the document.")

            embeddings = self._embedding_service.embed(
                [chunk.text for chunk in chunks]
            )
            self._vector_store.replace_document(document.id, chunks, embeddings)
            if not self._repository.update_status(
                document.id,
                DocumentStatus.READY,
                None,
                datetime.now(timezone.utc),
            ):
                raise RuntimeError("The document record disappeared during processing.")
        except Exception as exc:
            logger.exception("Document ingestion failed for %s", document_id)
            self._cleanup_vectors(document_id)
            self._mark_failed(document_id, exc)

    def _cleanup_vectors(self, document_id: UUID) -> None:
        try:
            self._vector_store.delete_document(document_id)
        except Exception:
            logger.exception(
                "Could not clean up vectors after ingestion failure for %s",
                document_id,
            )

    def _mark_failed(self, document_id: UUID, exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        error_message = message[:_MAX_ERROR_MESSAGE_LENGTH]
        try:
            updated = self._repository.update_status(
                document_id,
                DocumentStatus.FAILED,
                error_message,
                datetime.now(timezone.utc),
            )
            if not updated:
                logger.error(
                    "Could not mark missing document %s as failed",
                    document_id,
                )
        except Exception:
            logger.exception("Could not mark document %s as failed", document_id)