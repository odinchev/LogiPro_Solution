"""Tests for local embeddings and Chroma payload construction."""

from uuid import uuid4

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.models.ingestion import TextChunk
from app.services.embedding_service import SentenceTransformerEmbeddingService
from app.services.vector_store_service import ChromaVectorStore


class FakeEmbeddings:
    def tolist(self) -> list[list[float]]:
        return [[0.1, 0.2], [0.3, 0.4]]


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, texts: list[str], **kwargs) -> FakeEmbeddings:
        self.calls.append((texts, kwargs))
        return FakeEmbeddings()


class FakeCollection:
    def __init__(self) -> None:
        self.deleted: list[dict[str, str]] = []
        self.upserts: list[dict[str, object]] = []
        self.queries: list[dict[str, object]] = []

    def delete(self, *, where: dict[str, str]) -> None:
        self.deleted.append(where)

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "ids": [["document:p0002:c0000"]],
            "documents": [["gross weight"]],
            "metadatas": [[{"page_number": 2, "filename": "shipment.pdf"}]],
            "distances": [[0.25]],
        }


def test_sentence_transformer_service_requests_normalized_embeddings() -> None:
    model = FakeSentenceTransformer()
    service = SentenceTransformerEmbeddingService(
        model_name="local-model",
        device="cpu",
        batch_size=8,
    )
    service._model = model

    result = service.embed(["first", "second"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert model.calls == [
        (
            ["first", "second"],
            {
                "batch_size": 8,
                "show_progress_bar": False,
                "convert_to_numpy": True,
                "normalize_embeddings": True,
            },
        )
    ]


def test_chroma_store_upserts_documents_embeddings_and_page_metadata(tmp_path) -> None:
    document_id = uuid4()
    chunks = [
        TextChunk(
            id=f"{document_id}:p0002:c0000",
            document_id=document_id,
            filename="shipment.pdf",
            page_number=2,
            chunk_index=0,
            char_start=10,
            char_end=22,
            extraction_method="tesseract",
            text="gross weight",
        )
    ]
    collection = FakeCollection()
    store = ChromaVectorStore(
        persist_directory=tmp_path,
        collection_name="test_chunks",
        batch_size=100,
    )
    store._collection = collection

    store.replace_document(document_id, chunks, [[0.1, 0.2]])

    assert collection.deleted == [{"document_id": str(document_id)}]
    assert collection.upserts == [
        {
            "ids": [chunks[0].id],
            "documents": ["gross weight"],
            "embeddings": [[0.1, 0.2]],
            "metadatas": [
                {
                    "document_id": str(document_id),
                    "filename": "shipment.pdf",
                    "page_number": 2,
                    "chunk_index": 0,
                    "char_start": 10,
                    "char_end": 22,
                    "extraction_method": "tesseract",
                }
            ],
        }
    ]


def test_chroma_store_persists_chunks_locally(tmp_path) -> None:
    document_id = uuid4()
    collection_name = "integration_chunks"
    chunk = TextChunk(
        id=f"{document_id}:p0001:c0000",
        document_id=document_id,
        filename="delivery.png",
        page_number=1,
        chunk_index=0,
        char_start=0,
        char_end=13,
        extraction_method="tesseract",
        text="delivery note",
    )
    store = ChromaVectorStore(
        persist_directory=tmp_path,
        collection_name=collection_name,
        batch_size=100,
    )

    store.replace_document(document_id, [chunk], [[0.1, 0.2]])

    client = chromadb.PersistentClient(
        path=str(tmp_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_collection(
        name=collection_name,
        embedding_function=None,
    )
    result = collection.get(
        ids=[chunk.id],
        include=["documents", "metadatas", "embeddings"],
    )
    assert result["ids"] == [chunk.id]
    assert result["documents"] == ["delivery note"]
    assert result["metadatas"][0]["page_number"] == 1
    assert result["embeddings"] is not None


def test_chroma_search_maps_results_and_filters_by_document(tmp_path) -> None:
    document_id = uuid4()
    collection = FakeCollection()
    store = ChromaVectorStore(
        persist_directory=tmp_path,
        collection_name="test_chunks",
        batch_size=100,
    )
    store._collection = collection

    results = store.search_document(document_id, [0.1, 0.2], 3)

    assert collection.queries == [
        {
            "query_embeddings": [[0.1, 0.2]],
            "n_results": 3,
            "where": {"document_id": str(document_id)},
            "include": ["documents", "metadatas", "distances"],
        }
    ]
    assert len(results) == 1
    assert results[0].id == "document:p0002:c0000"
    assert results[0].page_number == 2
    assert results[0].text == "gross weight"
    assert results[0].relevance_score == 0.8


def test_chroma_search_never_returns_chunks_from_another_document(tmp_path) -> None:
    first_document = uuid4()
    second_document = uuid4()
    store = ChromaVectorStore(
        persist_directory=tmp_path,
        collection_name="filtered_chunks",
        batch_size=100,
    )
    chunks = [
        TextChunk(
            id=f"{first_document}:p0001:c0000",
            document_id=first_document,
            filename="first.pdf",
            page_number=1,
            chunk_index=0,
            char_start=0,
            char_end=10,
            extraction_method="pypdf",
            text="first text",
        ),
        TextChunk(
            id=f"{second_document}:p0005:c0000",
            document_id=second_document,
            filename="second.pdf",
            page_number=5,
            chunk_index=0,
            char_start=0,
            char_end=11,
            extraction_method="pypdf",
            text="second text",
        ),
    ]
    store.replace_document(first_document, [chunks[0]], [[1.0, 0.0]])
    store.replace_document(second_document, [chunks[1]], [[1.0, 0.0]])

    results = store.search_document(first_document, [1.0, 0.0], 5)

    assert [chunk.id for chunk in results] == [chunks[0].id]
    assert results[0].page_number == 1