"""Domain types for extracted pages and vector-ready text chunks."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """Text extracted from one one-based document page or image frame."""

    page_number: int
    text: str
    extraction_method: str


@dataclass(frozen=True, slots=True)
class TextChunk:
    """A page-scoped text segment and its source metadata."""

    id: str
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    char_start: int
    char_end: int
    extraction_method: str
    text: str