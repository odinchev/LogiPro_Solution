"""Local ChromaDB persistence for embedded document chunks."""

import math
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import UUID

from app.models.ingestion import TextChunk
from app.models.query import RetrievedChunk


class VectorStore(Protocol):
    """Persistence operations required by the ingestion pipeline."""

    def replace_document(
        self,
        document_id: UUID,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Replace all vectors belonging to one document."""
        ...

    def delete_document(self, document_id: UUID) -> None:
        """Delete all vectors belonging to one document."""
        ...

    def search_document(
        self,
        document_id: UUID,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Return similarity-ranked chunks belonging to one document."""
        ...


class ChromaVectorStore:
    """Persist caller-generated embeddings in a local Chroma collection."""

    def __init__(
        self,
        *,
        persist_directory: Path,
        collection_name: str,
        batch_size: int,
    ) -> None:
        self._persist_directory = persist_directory
        self._collection_name = collection_name
        self._batch_size = batch_size
        self._client: Any | None = None
        self._collection: Any | None = None
        self._lock = Lock()

    def replace_document(
        self,
        document_id: UUID,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Delete stale vectors and upsert a complete document in batches."""
        if len(chunks) != len(embeddings):
            raise ValueError("Each text chunk must have exactly one embedding.")

        with self._lock:
            collection = self._get_collection()
            document_filter = {"document_id": str(document_id)}
            collection.delete(where=document_filter)
            try:
                for offset in range(0, len(chunks), self._batch_size):
                    chunk_batch = chunks[offset : offset + self._batch_size]
                    embedding_batch = embeddings[offset : offset + self._batch_size]
                    collection.upsert(
                        ids=[chunk.id for chunk in chunk_batch],
                        documents=[chunk.text for chunk in chunk_batch],
                        embeddings=embedding_batch,
                        metadatas=[self._metadata(chunk) for chunk in chunk_batch],
                    )
            except Exception:
                collection.delete(where=document_filter)
                raise

    def delete_document(self, document_id: UUID) -> None:
        """Delete vectors for one document when processing fails."""
        with self._lock:
            self._get_collection().delete(
                where={"document_id": str(document_id)}
            )

    def search_document(
        self,
        document_id: UUID,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Search vectors scoped to a single document UUID."""
        with self._lock:
            results = self._get_collection().query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"document_id": str(document_id)},
                include=["documents", "metadatas", "distances"],
            )

        ids = self._first_batch(results.get("ids"))
        documents = self._first_batch(results.get("documents"))
        metadatas = self._first_batch(results.get("metadatas"))
        distances = self._first_batch(results.get("distances"))

        chunks: list[RetrievedChunk] = []
        for chunk_id, text, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
        ):
            if text is None or metadata is None:
                continue
            numeric_distance = max(float(distance), 0.0)
            if not math.isfinite(numeric_distance):
                numeric_distance = float("inf")
            chunks.append(
                RetrievedChunk(
                    id=str(chunk_id),
                    text=str(text),
                    page_number=int(metadata["page_number"]),
                    filename=str(metadata.get("filename", "unknown")),
                    relevance_score=1.0 / (1.0 + numeric_distance),
                )
            )
        return chunks

    def _get_collection(self) -> Any:
        if self._collection is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self._persist_directory.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self._persist_directory),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=None,
            )
        return self._collection

    @staticmethod
    def _metadata(chunk: TextChunk) -> dict[str, str | int]:
        return {
            "document_id": str(chunk.document_id),
            "filename": chunk.filename,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "extraction_method": chunk.extraction_method,
        }

    @staticmethod
    def _first_batch(value: Any) -> list[Any]:
        if not value:
            return []
        return list(value[0])