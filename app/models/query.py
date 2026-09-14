"""Internal retrieval and answer-generation domain types."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A similarity-ranked document chunk returned by the vector store."""

    id: str
    text: str
    page_number: int
    filename: str
    relevance_score: float


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """Answer text and information about the provider that produced it."""

    text: str
    provider: str
    used_fallback: bool