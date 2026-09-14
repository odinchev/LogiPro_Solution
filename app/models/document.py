"""Document domain types used by services and repositories."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID


class DocumentStatus(str, Enum):
    """States a document can occupy during asynchronous processing."""

    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Persisted metadata for one uploaded document."""

    id: UUID
    filename: str
    path: Path
    status: DocumentStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime