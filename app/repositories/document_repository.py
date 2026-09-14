"""Document repository contract."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.models.document import DocumentRecord, DocumentStatus


class DocumentRepository(Protocol):
    """Persistence operations required by the document service."""

    def initialize(self) -> None:
        """Create persistence structures when they do not exist."""
        ...

    def create(self, document: DocumentRecord) -> None:
        """Persist a newly uploaded document."""
        ...

    def get_by_id(self, document_id: UUID) -> DocumentRecord | None:
        """Return one document, or ``None`` when it does not exist."""
        ...

    def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        error_message: str | None,
        updated_at: datetime,
    ) -> bool:
        """Update processing state and return whether the document existed."""
        ...