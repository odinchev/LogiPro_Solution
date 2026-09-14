"""Local sentence-transformer embedding generation."""

from threading import Lock
from typing import Any, Protocol


class EmbeddingService(Protocol):
    """Generate dense vectors for a batch of text chunks."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input string."""
        ...


class SentenceTransformerEmbeddingService:
    """Lazily load and run a local sentence-transformers model."""

    def __init__(self, *, model_name: str, device: str, batch_size: int) -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._model: Any | None = None
        self._lock = Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized embeddings for all supplied texts."""
        if not texts:
            return []

        with self._lock:
            model = self._get_model()
            embeddings = model.encode(
                texts,
                batch_size=self._batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        return embeddings.tolist()

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self._model_name,
                device=self._device,
            )
        return self._model