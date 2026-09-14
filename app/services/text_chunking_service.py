"""Page-aware deterministic character chunking."""

from uuid import UUID

from app.models.ingestion import ExtractedPage, TextChunk


class TextChunkingService:
    """Split extracted pages into overlapping chunks without crossing pages."""

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk_pages(
        self,
        *,
        document_id: UUID,
        filename: str,
        pages: list[ExtractedPage],
    ) -> list[TextChunk]:
        """Return stable, page-scoped chunks and character offsets."""
        chunks: list[TextChunk] = []
        step = self._chunk_size - self._chunk_overlap

        for page in pages:
            chunk_index = 0
            for window_start in range(0, len(page.text), step):
                window_end = min(window_start + self._chunk_size, len(page.text))
                raw_chunk = page.text[window_start:window_end]
                text = raw_chunk.strip()
                if text:
                    leading_whitespace = len(raw_chunk) - len(raw_chunk.lstrip())
                    char_start = window_start + leading_whitespace
                    chunks.append(
                        TextChunk(
                            id=(
                                f"{document_id}:p{page.page_number:04d}:"
                                f"c{chunk_index:04d}"
                            ),
                            document_id=document_id,
                            filename=filename,
                            page_number=page.page_number,
                            chunk_index=chunk_index,
                            char_start=char_start,
                            char_end=char_start + len(text),
                            extraction_method=page.extraction_method,
                            text=text,
                        )
                    )
                    chunk_index += 1

                if window_end == len(page.text):
                    break

        return chunks