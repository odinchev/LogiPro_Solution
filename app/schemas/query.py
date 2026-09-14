"""Question-answering API contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    """A natural-language question scoped to one uploaded document."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    """A retrieved document chunk supporting an answer."""

    chunk_id: str
    page_number: int | None = Field(default=None, ge=1)
    text: str
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)


class QueryResponse(BaseModel):
    """Generated answer with traceable source chunks."""

    document_id: UUID
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    llm_provider: str
    used_fallback: bool = False