"""SQLite implementation of document metadata persistence."""

import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.document import DocumentRecord, DocumentStatus

_CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('PROCESSING', 'READY', 'FAILED')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class SQLiteDocumentRepository:
    """Store document metadata in a local SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        """Create the database directory and documents table if needed."""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(_CREATE_DOCUMENTS_TABLE)

    def create(self, document: DocumentRecord) -> None:
        """Insert a new document record."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id,
                    filename,
                    path,
                    status,
                    error_message,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(document.id),
                    document.filename,
                    str(document.path),
                    document.status.value,
                    document.error_message,
                    document.created_at.isoformat(),
                    document.updated_at.isoformat(),
                ),
            )

    def get_by_id(self, document_id: UUID) -> DocumentRecord | None:
        """Retrieve a document record by UUID."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, filename, path, status, error_message, created_at, updated_at
                FROM documents
                WHERE id = ?
                """,
                (str(document_id),),
            ).fetchone()

        if row is None:
            return None

        return DocumentRecord(
            id=UUID(row["id"]),
            filename=row["filename"],
            path=Path(row["path"]),
            status=DocumentStatus(row["status"]),
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        error_message: str | None,
        updated_at: datetime,
    ) -> bool:
        """Update a document's processing state and timestamp."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE documents
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    error_message,
                    updated_at.isoformat(),
                    str(document_id),
                ),
            )
            return cursor.rowcount == 1