"""Document ingestion and status use cases."""

from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from uuid import UUID
from uuid import uuid4

from app.models.document import DocumentRecord, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentStatusResponse, DocumentUploadResponse
from app.services.exceptions import (
    DocumentNotFoundError,
    InvalidUploadError,
    UnsupportedDocumentTypeError,
)

_CHUNK_SIZE = 1024 * 1024
_ALLOWED_MEDIA_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".tif": frozenset({"image/tiff"}),
    ".tiff": frozenset({"image/tiff"}),
    ".bmp": frozenset({"image/bmp", "image/x-ms-bmp"}),
    ".webp": frozenset({"image/webp"}),
}


class DocumentService:
    """Coordinate document persistence and asynchronous processing."""

    def __init__(
        self,
        repository: DocumentRepository,
        upload_dir: Path,
    ) -> None:
        self._repository = repository
        self._upload_dir = upload_dir

    def create_document(
        self,
        *,
        filename: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> DocumentUploadResponse:
        """Validate, store, and record a document awaiting processing."""
        safe_filename, suffix, normalized_content_type = self._validate_file_type(
            filename=filename,
            content_type=content_type,
        )

        document_id = uuid4()
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        destination = (self._upload_dir / f"{document_id}{suffix}").resolve()
        temporary_path = destination.with_suffix(f"{destination.suffix}.part")

        saved = False
        try:
            byte_count = self._write_stream(stream, temporary_path)
            if byte_count == 0:
                raise InvalidUploadError("The uploaded file is empty.")

            temporary_path.replace(destination)
            saved = True

            now = datetime.now(timezone.utc)
            document = DocumentRecord(
                id=document_id,
                filename=safe_filename,
                path=destination,
                status=DocumentStatus.PROCESSING,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
            self._repository.create(document)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            if saved:
                destination.unlink(missing_ok=True)
            raise

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            content_type=normalized_content_type,
            status=document.status,
            created_at=document.created_at,
        )

    def get_document_status(self, document_id: UUID) -> DocumentStatusResponse:
        """Return the current state of a submitted document."""
        document = self._repository.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)

        return DocumentStatusResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            created_at=document.created_at,
            updated_at=document.updated_at,
            error_message=document.error_message,
        )

    @staticmethod
    def _validate_file_type(
        *,
        filename: str,
        content_type: str | None,
    ) -> tuple[str, str, str]:
        safe_filename = Path(filename.replace("\\", "/")).name.strip()
        if not safe_filename or safe_filename in {".", ".."}:
            raise InvalidUploadError("The uploaded file must have a filename.")

        suffix = Path(safe_filename).suffix.lower()
        normalized_content_type = (content_type or "").split(";", maxsplit=1)[0].lower()
        allowed_media_types = _ALLOWED_MEDIA_TYPES.get(suffix)
        if (
            allowed_media_types is None
            or normalized_content_type not in allowed_media_types
        ):
            raise UnsupportedDocumentTypeError(
                "Only PDF, JPEG, PNG, TIFF, BMP, and WebP documents are supported."
            )

        return safe_filename, suffix, normalized_content_type

    @staticmethod
    def _write_stream(stream: BinaryIO, destination: Path) -> int:
        byte_count = 0
        with destination.open("xb") as output:
            while chunk := stream.read(_CHUNK_SIZE):
                output.write(chunk)
                byte_count += len(chunk)
        return byte_count