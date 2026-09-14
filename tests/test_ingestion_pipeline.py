"""Tests for chunking and background ingestion orchestration."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.document import DocumentRecord, DocumentStatus
from app.models.ingestion import ExtractedPage, TextChunk
from app.repositories.sqlite_document_repository import SQLiteDocumentRepository
from app.services.document_ingestion_service import DocumentIngestionService
from app.services.text_chunking_service import TextChunkingService


class StubExtractor:
    def __init__(
        self,
        pages: list[ExtractedPage] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.pages = pages or []
        self.error = error
        self.paths: list[Path] = []

    def extract(self, document_path: Path) -> list[ExtractedPage]:
        self.paths.append(document_path)
        if self.error is not None:
            raise self.error
        return self.pages


class RecordingEmbeddingService:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts = texts
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


class RecordingVectorStore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.replacements: list[tuple[UUID, list[TextChunk], list[list[float]]]] = []
        self.deleted: list[UUID] = []

    def replace_document(
        self,
        document_id: UUID,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> None:
        if self.error is not None:
            raise self.error
        self.replacements.append((document_id, chunks, embeddings))

    def delete_document(self, document_id: UUID) -> None:
        self.deleted.append(document_id)

    def search_document(
        self,
        document_id: UUID,
        query_embedding: list[float],
        top_k: int,
    ) -> list:
        del document_id, query_embedding, top_k
        return []


class FailingReadRepository:
    def get_by_id(self, document_id: UUID) -> DocumentRecord | None:
        raise RuntimeError("database read failed")

    def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        error_message: str | None,
        updated_at: datetime,
    ) -> bool:
        self.updated = (document_id, status, error_message, updated_at)
        return True


def create_processing_document(
    repository: SQLiteDocumentRepository,
    document_path: Path,
) -> DocumentRecord:
    now = datetime.now(timezone.utc)
    document = DocumentRecord(
        id=uuid4(),
        filename="shipment.pdf",
        path=document_path,
        status=DocumentStatus.PROCESSING,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    repository.create(document)
    return document


def test_chunker_preserves_pages_offsets_and_overlap() -> None:
    document_id = uuid4()
    chunker = TextChunkingService(chunk_size=10, chunk_overlap=3)

    chunks = chunker.chunk_pages(
        document_id=document_id,
        filename="shipment.pdf",
        pages=[
            ExtractedPage(1, "ABCDEFGHIJKLMNO", "pypdf"),
            ExtractedPage(2, "page two", "tesseract"),
        ],
    )

    assert [(chunk.page_number, chunk.text) for chunk in chunks] == [
        (1, "ABCDEFGHIJ"),
        (1, "HIJKLMNO"),
        (2, "page two"),
    ]
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == 10
    assert chunks[1].char_start == 7
    assert chunks[1].id == f"{document_id}:p0001:c0001"
    assert chunks[2].id == f"{document_id}:p0002:c0000"
    assert chunks[2].extraction_method == "tesseract"


def test_successful_pipeline_stores_vectors_and_marks_ready(tmp_path: Path) -> None:
    repository = SQLiteDocumentRepository(tmp_path / "documents.sqlite3")
    repository.initialize()
    document = create_processing_document(repository, tmp_path / "shipment.pdf")
    extractor = StubExtractor(
        [
            ExtractedPage(1, "Bill of lading number ABC123", "pypdf"),
            ExtractedPage(2, "Gross weight 2500 kg", "tesseract"),
        ]
    )
    embeddings = RecordingEmbeddingService()
    vectors = RecordingVectorStore()
    service = DocumentIngestionService(
        repository=repository,
        text_extractor=extractor,
        text_chunker=TextChunkingService(chunk_size=500, chunk_overlap=50),
        embedding_service=embeddings,
        vector_store=vectors,
    )

    service.process_document(document.id)

    updated = repository.get_by_id(document.id)
    assert updated is not None
    assert updated.status is DocumentStatus.READY
    assert updated.error_message is None
    assert updated.updated_at >= document.updated_at
    assert extractor.paths == [document.path]
    assert embeddings.texts == [
        "Bill of lading number ABC123",
        "Gross weight 2500 kg",
    ]
    assert len(vectors.replacements) == 1
    stored_id, stored_chunks, stored_embeddings = vectors.replacements[0]
    assert stored_id == document.id
    assert [chunk.page_number for chunk in stored_chunks] == [1, 2]
    assert stored_embeddings == [[0.0, 1.0], [1.0, 1.0]]


@pytest.mark.parametrize(
    ("extractor", "vector_error", "expected_error"),
    [
        (StubExtractor([]), None, "No usable text"),
        (StubExtractor(error=RuntimeError("OCR unavailable")), None, "OCR unavailable"),
        (
            StubExtractor([ExtractedPage(1, "shipment text", "pypdf")]),
            RuntimeError("vector write failed"),
            "vector write failed",
        ),
    ],
)
def test_pipeline_failure_cleans_vectors_and_marks_failed(
    tmp_path: Path,
    extractor: StubExtractor,
    vector_error: Exception | None,
    expected_error: str,
) -> None:
    repository = SQLiteDocumentRepository(tmp_path / "documents.sqlite3")
    repository.initialize()
    document = create_processing_document(repository, tmp_path / "shipment.pdf")
    vectors = RecordingVectorStore(vector_error)
    service = DocumentIngestionService(
        repository=repository,
        text_extractor=extractor,
        text_chunker=TextChunkingService(chunk_size=500, chunk_overlap=50),
        embedding_service=RecordingEmbeddingService(),
        vector_store=vectors,
    )

    service.process_document(document.id)

    updated = repository.get_by_id(document.id)
    assert updated is not None
    assert updated.status is DocumentStatus.FAILED
    assert updated.error_message is not None
    assert expected_error in updated.error_message
    assert vectors.deleted == [document.id]


def test_pipeline_truncates_failure_message(tmp_path: Path) -> None:
    repository = SQLiteDocumentRepository(tmp_path / "documents.sqlite3")
    repository.initialize()
    document = create_processing_document(repository, tmp_path / "shipment.pdf")
    service = DocumentIngestionService(
        repository=repository,
        text_extractor=StubExtractor(error=RuntimeError("x" * 3_000)),
        text_chunker=TextChunkingService(chunk_size=500, chunk_overlap=50),
        embedding_service=RecordingEmbeddingService(),
        vector_store=RecordingVectorStore(),
    )

    service.process_document(document.id)

    updated = repository.get_by_id(document.id)
    assert updated is not None
    assert updated.status is DocumentStatus.FAILED
    assert updated.error_message is not None
    assert len(updated.error_message) == 2_000


def test_pipeline_skips_document_that_is_already_ready(tmp_path: Path) -> None:
    repository = SQLiteDocumentRepository(tmp_path / "documents.sqlite3")
    repository.initialize()
    document = create_processing_document(repository, tmp_path / "shipment.pdf")
    repository.update_status(
        document.id,
        DocumentStatus.READY,
        None,
        datetime.now(timezone.utc),
    )
    extractor = StubExtractor(error=AssertionError("extractor should not run"))
    service = DocumentIngestionService(
        repository=repository,
        text_extractor=extractor,
        text_chunker=TextChunkingService(chunk_size=500, chunk_overlap=50),
        embedding_service=RecordingEmbeddingService(),
        vector_store=RecordingVectorStore(),
    )

    service.process_document(document.id)

    assert extractor.paths == []


def test_pipeline_attempts_failed_status_when_document_read_fails() -> None:
    repository = FailingReadRepository()
    document_id = uuid4()
    service = DocumentIngestionService(
        repository=repository,
        text_extractor=StubExtractor(),
        text_chunker=TextChunkingService(chunk_size=500, chunk_overlap=50),
        embedding_service=RecordingEmbeddingService(),
        vector_store=RecordingVectorStore(),
    )

    service.process_document(document_id)

    assert repository.updated[0] == document_id
    assert repository.updated[1] is DocumentStatus.FAILED
    assert repository.updated[2] == "database read failed"