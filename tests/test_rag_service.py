"""Tests for readiness checks, retrieval, answers, and citations."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.document import DocumentRecord, DocumentStatus
from app.models.query import GeneratedAnswer, RetrievedChunk
from app.schemas.query import QueryRequest
from app.services.exceptions import (
    DocumentNotFoundError,
    DocumentNotReadyError,
    RelevantContextNotFoundError,
)
from app.services.rag_service import RagService


class StubRepository:
    def __init__(self, document: DocumentRecord | None) -> None:
        self.document = document

    def get_by_id(self, document_id: UUID) -> DocumentRecord | None:
        return self.document if self.document and self.document.id == document_id else None


class RecordingEmbeddings:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts = texts
        return [[0.25, 0.75]]


class RecordingVectorStore:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.searches: list[tuple[UUID, list[float], int]] = []

    def search_document(
        self,
        document_id: UUID,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        self.searches.append((document_id, query_embedding, top_k))
        return self.chunks


class RecordingAnswerGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[RetrievedChunk], str | None]] = []

    def generate(
        self,
        *,
        question: str,
        chunks: list[RetrievedChunk],
        model: str | None = None,
    ) -> GeneratedAnswer:
        self.calls.append((question, chunks, model))
        return GeneratedAnswer("The gross weight is 2500 kg [1].", "mock", True)


def document_with_status(status: DocumentStatus, error: str | None = None) -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(
        id=uuid4(),
        filename="shipment.pdf",
        path=Path("shipment.pdf"),
        status=status,
        error_message=error,
        created_at=now,
        updated_at=now,
    )


def build_service(
    document: DocumentRecord | None,
    chunks: list[RetrievedChunk] | None = None,
) -> tuple[RagService, RecordingEmbeddings, RecordingVectorStore, RecordingAnswerGenerator]:
    embeddings = RecordingEmbeddings()
    vectors = RecordingVectorStore(chunks or [])
    answers = RecordingAnswerGenerator()
    service = RagService(
        repository=StubRepository(document),
        embedding_service=embeddings,
        vector_store=vectors,
        answer_generator=answers,
    )
    return service, embeddings, vectors, answers


def test_query_requires_existing_document() -> None:
    service, embeddings, vectors, _ = build_service(None)
    document_id = uuid4()

    with pytest.raises(DocumentNotFoundError):
        service.query_document(
            document_id=document_id,
            request=QueryRequest(question="What is the weight?"),
        )

    assert embeddings.texts == []
    assert vectors.searches == []


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (DocumentStatus.PROCESSING, None),
        (DocumentStatus.FAILED, "OCR failed"),
    ],
)
def test_query_checks_readiness_before_embedding(
    status: DocumentStatus,
    error: str | None,
) -> None:
    document = document_with_status(status, error)
    service, embeddings, vectors, _ = build_service(document)

    with pytest.raises(DocumentNotReadyError) as exception:
        service.query_document(
            document_id=document.id,
            request=QueryRequest(question="What is the weight?"),
        )

    assert exception.value.status is status
    assert embeddings.texts == []
    assert vectors.searches == []


def test_query_returns_answer_and_page_citations() -> None:
    document = document_with_status(DocumentStatus.READY)
    chunks = [
        RetrievedChunk(
            id=f"{document.id}:p0002:c0000",
            text="Gross weight: 2500 kg",
            page_number=2,
            filename=document.filename,
            relevance_score=0.9,
        ),
        RetrievedChunk(
            id=f"{document.id}:p0003:c0000",
            text="Destination: Rotterdam",
            page_number=3,
            filename=document.filename,
            relevance_score=0.7,
        ),
    ]
    service, embeddings, vectors, answers = build_service(document, chunks)
    request = QueryRequest(question="What is the weight?", top_k=2)

    result = service.query_document(document_id=document.id, request=request)

    assert embeddings.texts == ["What is the weight?"]
    assert vectors.searches == [(document.id, [0.25, 0.75], 2)]
    assert answers.calls == [("What is the weight?", chunks, None)]
    assert result.answer == "The gross weight is 2500 kg [1]."
    assert result.llm_provider == "mock"
    assert result.used_fallback is True
    assert [citation.page_number for citation in result.citations] == [2, 3]
    assert result.citations[0].text == "Gross weight: 2500 kg"
    assert result.citations[0].relevance_score == 0.9


def test_query_rejects_ready_document_without_context() -> None:
    document = document_with_status(DocumentStatus.READY)
    service, _, _, answers = build_service(document)

    with pytest.raises(RelevantContextNotFoundError):
        service.query_document(
            document_id=document.id,
            request=QueryRequest(question="What is the weight?"),
        )

    assert answers.calls == []


def test_query_forwards_custom_model_to_answer_generator() -> None:
    document = document_with_status(DocumentStatus.READY)
    chunks = [
        RetrievedChunk(
            id=f"{document.id}:p0001:c0000",
            text="Weight: 100 kg",
            page_number=1,
            filename=document.filename,
            relevance_score=0.95,
        ),
    ]
    service, _, _, answers = build_service(document, chunks)
    request = QueryRequest(
        question="What is the weight?",
        model="custom-model:latest",
    )

    service.query_document(document_id=document.id, request=request)

    assert answers.calls == [("What is the weight?", chunks, "custom-model:latest")]