"""Application-specific service errors."""

from uuid import UUID

from app.models.document import DocumentStatus


class InvalidUploadError(ValueError):
    """Raised when an upload has no usable filename or content."""


class UnsupportedDocumentTypeError(ValueError):
    """Raised when an upload is not a supported PDF or image."""


class DocumentNotFoundError(LookupError):
    """Raised when a requested document does not exist."""

    def __init__(self, document_id: UUID) -> None:
        super().__init__(f"Document '{document_id}' was not found.")
        self.document_id = document_id


class DocumentNotReadyError(RuntimeError):
    """Raised when a document cannot be queried in its current state."""

    def __init__(
        self,
        document_id: UUID,
        status: DocumentStatus,
        error_message: str | None = None,
    ) -> None:
        if status is DocumentStatus.PROCESSING:
            message = f"Document '{document_id}' is still processing."
        else:
            detail = f" Processing error: {error_message}" if error_message else ""
            message = f"Document '{document_id}' failed processing.{detail}"
        super().__init__(message)
        self.document_id = document_id
        self.status = status


class RelevantContextNotFoundError(RuntimeError):
    """Raised when a ready document has no retrievable vector chunks."""


class LlmUnavailableError(RuntimeError):
    """Raised when Ollama is required but cannot generate an answer."""

