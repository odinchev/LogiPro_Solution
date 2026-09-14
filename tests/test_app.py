"""Application smoke, upload, and persistence tests."""

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.document import DocumentStatus
from app.repositories.sqlite_document_repository import SQLiteDocumentRepository
from app.schemas.query import Citation, QueryResponse
from app.services.exceptions import LlmUnavailableError


class RecordingDocumentProcessor:
    """Record task execution without invoking OCR or model infrastructure."""

    def __init__(self) -> None:
        self.document_ids: list[UUID] = []

    def process_document(self, document_id: UUID) -> None:
        self.document_ids.append(document_id)


class ReadyDocumentProcessor:
    """Simulate successful background processing through real SQLite state."""

    def __init__(self, repository: SQLiteDocumentRepository) -> None:
        self._repository = repository

    def process_document(self, document_id: UUID) -> None:
        self._repository.update_status(
            document_id,
            DocumentStatus.READY,
            None,
            datetime.now(timezone.utc),
        )


class SuccessfulQueryService:
    def query_document(self, *, document_id: UUID, request) -> QueryResponse:
        return QueryResponse(
            document_id=document_id,
            question=request.question,
            answer="The gross weight is 2500 kg [1].",
            citations=[
                Citation(
                    chunk_id=f"{document_id}:p0002:c0000",
                    page_number=2,
                    text="Gross weight: 2500 kg",
                    relevance_score=0.9,
                )
            ],
            llm_provider="mock",
            used_fallback=True,
        )


class UnavailableQueryService:
    def query_document(self, *, document_id: UUID, request) -> QueryResponse:
        del document_id, request
        raise LlmUnavailableError("Ollama is required but unavailable.")


@pytest.fixture
def test_app(tmp_path: Path) -> FastAPI:
    """Build an application with fully isolated local storage."""
    processor = RecordingDocumentProcessor()
    application = create_app(
        Settings(environment="testing", data_dir=tmp_path),
        document_processor=processor,
    )
    application.state.recording_document_processor = processor
    return application


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """Run startup and shutdown around each test client."""
    with TestClient(test_app) as test_client:
        yield test_client


def test_frontend_is_served_at_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "LogiPro Document Intelligence" in response.text
    assert 'id="upload-form"' in response.text
    assert 'id="status-badge"' in response.text
    assert 'id="qa-fieldset"' in response.text
    assert 'id="answer-list"' in response.text
    assert "/assets/styles.css" in response.text
    assert "/assets/app.js" in response.text


def test_service_info(client: TestClient) -> None:
    response = client.get("/api/info")

    assert response.status_code == 200
    assert response.json()["name"] == "LogiPro Document Intelligence Service"
    assert response.json()["environment"] == "testing"
    assert response.json()["docs_url"] == "/docs"


def test_frontend_assets_are_served(client: TestClient) -> None:
    styles = client.get("/assets/styles.css")
    script = client.get("/assets/app.js")

    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert ".status-ready" in styles.text
    assert ".citation-snippet" in styles.text
    assert "white-space: pre" not in styles.text

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert 'fetch("/api/documents/upload"' in script.text
    assert "/status`" in script.text
    assert "/query`" in script.text
    assert "window.setTimeout" in script.text
    assert "citation.page_number" in script.text
    assert "citation.relevance_score" in script.text
    assert "innerHTML" not in script.text


def test_health_check(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_exposes_document_contracts(client: TestClient) -> None:
    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/documents/upload" in paths
    assert "/api/documents/{document_id}/status" in paths
    assert "/api/documents/{document_id}/query" in paths


def test_pdf_upload_persists_file_and_processing_record(
    client: TestClient,
    test_app: FastAPI,
) -> None:
    content = b"%PDF-1.7\nshipping document"

    response = client.post(
        "/api/documents/upload",
        files={"file": ("bill-of-lading.pdf", content, "application/pdf")},
    )

    assert response.status_code == 202
    payload = response.json()
    document_id = UUID(payload["document_id"])
    assert payload["filename"] == "bill-of-lading.pdf"
    assert payload["content_type"] == "application/pdf"
    assert payload["status"] == "PROCESSING"

    settings = test_app.state.settings
    stored_path = settings.upload_dir / f"{document_id}.pdf"
    assert stored_path.read_bytes() == content

    with sqlite3.connect(settings.sqlite_path) as connection:
        row = connection.execute(
            """
            SELECT id, filename, path, status, error_message, created_at, updated_at
            FROM documents
            WHERE id = ?
            """,
            (str(document_id),),
        ).fetchone()

    assert row is not None
    assert row[0] == str(document_id)
    assert row[1] == "bill-of-lading.pdf"
    assert Path(row[2]) == stored_path.resolve()
    assert row[3] == "PROCESSING"
    assert row[4] is None
    assert row[5] == row[6]
    assert test_app.state.recording_document_processor.document_ids == [document_id]


def test_image_upload_and_status_lookup(client: TestClient) -> None:
    response = client.post(
        "/api/documents/upload",
        files={"file": ("delivery-note.png", b"png-image", "image/png")},
    )

    assert response.status_code == 202
    document_id = response.json()["document_id"]

    status_response = client.get(f"/api/documents/{document_id}/status")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "document_id": document_id,
        "filename": "delivery-note.png",
        "status": "PROCESSING",
        "created_at": response.json()["created_at"],
        "updated_at": response.json()["created_at"],
        "error_message": None,
    }


def test_background_task_transition_is_visible_from_status_endpoint(
    tmp_path: Path,
) -> None:
    settings = Settings(environment="testing", data_dir=tmp_path)
    processor = ReadyDocumentProcessor(
        SQLiteDocumentRepository(settings.sqlite_path)
    )
    application = create_app(settings, document_processor=processor)

    with TestClient(application) as test_client:
        upload_response = test_client.post(
            "/api/documents/upload",
            files={"file": ("delivery.png", b"image", "image/png")},
        )
        status_response = test_client.get(
            f"/api/documents/{upload_response.json()['document_id']}/status"
        )

    assert upload_response.status_code == 202
    assert upload_response.json()["status"] == "PROCESSING"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "READY"
    assert status_response.json()["error_message"] is None


def test_upload_strips_client_path_from_filename(client: TestClient) -> None:
    response = client.post(
        "/api/documents/upload",
        files={"file": ("../../escape.pdf", b"%PDF-1.7", "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["filename"] == "escape.pdf"


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("notes.txt", "text/plain"),
        ("disguised.pdf", "image/png"),
        ("missing-type.png", "application/octet-stream"),
    ],
)
def test_upload_rejects_unsupported_or_mismatched_types(
    client: TestClient,
    filename: str,
    content_type: str,
) -> None:
    response = client.post(
        "/api/documents/upload",
        files={"file": (filename, b"content", content_type)},
    )

    assert response.status_code == 415
    assert "Only PDF" in response.json()["detail"]


def test_upload_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/documents/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is empty."


def test_unknown_document_returns_not_found(client: TestClient) -> None:
    document_id = uuid4()

    response = client.get(f"/api/documents/{document_id}/status")

    assert response.status_code == 404
    assert str(document_id) in response.json()["detail"]


def test_query_rejects_blank_question(client: TestClient) -> None:
    response = client.post(
        f"/api/documents/{uuid4()}/query",
        json={"question": "   "},
    )

    assert response.status_code == 422


def test_query_unknown_document_returns_not_found(client: TestClient) -> None:
    document_id = uuid4()
    response = client.post(
        f"/api/documents/{document_id}/query",
        json={"question": "What is the shipment weight?"},
    )

    assert response.status_code == 404
    assert str(document_id) in response.json()["detail"]


def test_query_processing_document_returns_conflict(client: TestClient) -> None:
    upload_response = client.post(
        "/api/documents/upload",
        files={"file": ("shipment.pdf", b"%PDF-1.7", "application/pdf")},
    )

    response = client.post(
        f"/api/documents/{upload_response.json()['document_id']}/query",
        json={"question": "What is the shipment weight?"},
    )

    assert response.status_code == 409
    assert response.json()["document_status"] == "PROCESSING"
    assert "still processing" in response.json()["detail"]


def test_query_failed_document_returns_conflict(
    client: TestClient,
    test_app: FastAPI,
) -> None:
    upload_response = client.post(
        "/api/documents/upload",
        files={"file": ("shipment.pdf", b"%PDF-1.7", "application/pdf")},
    )
    document_id = UUID(upload_response.json()["document_id"])
    test_app.state.document_repository.update_status(
        document_id,
        DocumentStatus.FAILED,
        "OCR could not read the document",
        datetime.now(timezone.utc),
    )

    response = client.post(
        f"/api/documents/{document_id}/query",
        json={"question": "What is the shipment weight?"},
    )

    assert response.status_code == 409
    assert response.json()["document_status"] == "FAILED"
    assert "OCR could not read the document" in response.json()["detail"]


def test_query_endpoint_returns_answer_and_citations(tmp_path: Path) -> None:
    application = create_app(
        Settings(environment="testing", data_dir=tmp_path),
        document_processor=RecordingDocumentProcessor(),
        rag_service=SuccessfulQueryService(),
    )
    document_id = uuid4()

    with TestClient(application) as test_client:
        response = test_client.post(
            f"/api/documents/{document_id}/query",
            json={"question": "What is the shipment weight?", "top_k": 3},
        )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": str(document_id),
        "question": "What is the shipment weight?",
        "answer": "The gross weight is 2500 kg [1].",
        "citations": [
            {
                "chunk_id": f"{document_id}:p0002:c0000",
                "page_number": 2,
                "text": "Gross weight: 2500 kg",
                "relevance_score": 0.9,
            }
        ],
        "llm_provider": "mock",
        "used_fallback": True,
    }


def test_query_endpoint_maps_required_ollama_failure_to_503(tmp_path: Path) -> None:
    application = create_app(
        Settings(environment="testing", data_dir=tmp_path),
        document_processor=RecordingDocumentProcessor(),
        rag_service=UnavailableQueryService(),
    )

    with TestClient(application) as test_client:
        response = test_client.post(
            f"/api/documents/{uuid4()}/query",
            json={"question": "What is the shipment weight?"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Ollama is required but unavailable."