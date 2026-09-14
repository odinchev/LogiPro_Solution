"""Retrieval-augmented question-answering use cases."""

from uuid import UUID

from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.schemas.query import Citation, QueryRequest, QueryResponse
from app.services.answer_generation_service import AnswerGenerator
from app.services.embedding_service import EmbeddingService
from app.services.exceptions import (
    DocumentNotFoundError,
    DocumentNotReadyError,
    RelevantContextNotFoundError,
)
from app.services.vector_store_service import VectorStore


class RagService:
    """Retrieve relevant chunks and generate grounded answers."""

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        answer_generator: AnswerGenerator,
    ) -> None:
        self._repository = repository
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._answer_generator = answer_generator

    def query_document(
        self,
        *,
        document_id: UUID,
        request: QueryRequest,
    ) -> QueryResponse:
        """Answer a question using content from one processed document."""
        document = self._repository.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        if document.status is not DocumentStatus.READY:
            raise DocumentNotReadyError(
                document.id,
                document.status,
                document.error_message,
            )

        embeddings = self._embedding_service.embed([request.question])
        if len(embeddings) != 1:
            raise RuntimeError("Question embedding generation returned an invalid result.")

        chunks = self._vector_store.search_document(
            document.id,
            embeddings[0],
            request.top_k,
        )
        if not chunks:
            raise RelevantContextNotFoundError(
                f"No indexed context was found for document '{document.id}'."
            )

        generated = self._answer_generator.generate(
            question=request.question,
            chunks=chunks,
        )
        return QueryResponse(
            document_id=document.id,
            question=request.question,
            answer=generated.text,
            citations=[
                Citation(
                    chunk_id=chunk.id,
                    page_number=chunk.page_number,
                    text=chunk.text,
                    relevance_score=chunk.relevance_score,
                )
                for chunk in chunks
            ],
            llm_provider=generated.provider,
            used_fallback=generated.used_fallback,
        )