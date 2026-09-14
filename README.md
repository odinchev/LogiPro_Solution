# LogiPro Document Intelligence Service

Local-first prototype for asynchronous extraction and natural-language querying
of shipping PDFs and images.

## Implemented milestones

The service currently includes:

- A FastAPI application factory and composed routers.
- Pydantic v2 contracts for upload, status, and query workflows.
- Service-layer boundaries that keep business logic out of route handlers.
- A functional health check and OpenAPI documentation.
- Single-service Docker Compose scaffolding and persistent local data mounts.
- SQLite-backed document metadata and status lookup.
- Streamed local persistence for validated PDF and image uploads.
- FastAPI background ingestion after a successful upload.
- Per-page digital PDF extraction with Tesseract fallback for scanned pages.
- Page-aware overlapping text chunks and local sentence-transformer embeddings.
- Persistent local ChromaDB vector storage with citation-ready metadata.
- Document-scoped semantic search with page-numbered source citations.
- Optional local Ollama answers with an immediate grounded mock fallback.

No paid API key or hosted inference service is required.

The responsive browser interface is served directly by FastAPI from the same
container and origin as the API. It provides upload progress, automatic status
polling, a Q&A workspace that unlocks at `READY`, and page-numbered citations.

## Upload lifecycle

`POST /api/documents/upload` accepts the following matching filename extensions
and media types:

- PDF (`.pdf`, `application/pdf`)
- JPEG (`.jpg` or `.jpeg`, `image/jpeg`)
- PNG (`.png`, `image/png`)
- TIFF (`.tif` or `.tiff`, `image/tiff`)
- BMP (`.bmp`, `image/bmp` or `image/x-ms-bmp`)
- WebP (`.webp`, `image/webp`)

Accepted files are saved under `data/uploads` using a generated UUID filename.
Their original safe filename, server path, `PROCESSING` status, optional error,
and UTC timestamps are recorded in `data/documents.sqlite3`. After returning
`202 Accepted`, a FastAPI background task extracts and indexes the document. The
status endpoint reads the persisted record and returns `404` for unknown IDs.

The processing task transitions documents as follows:

```text
PROCESSING -> READY
           -> FAILED (with an error_message)
```

PDF pages first use `pypdf`. Pages with little or no digital text are rendered
locally and sent to Tesseract. Images, including multi-frame TIFF files, use
Tesseract directly. Text is split into 500-character chunks with 50-character
overlap without crossing page boundaries. Chroma metadata contains the document
ID, original filename, page number, chunk index, offsets, and extraction method.

The default local embedding model is
`sentence-transformers/all-MiniLM-L6-v2`; the Docker build caches it in the image
so processing does not need to download a model after startup.

## Ask questions

Only documents with status `READY` can be queried. `PROCESSING` and `FAILED`
documents return `409 Conflict`, and unknown IDs return `404 Not Found`.

```bash
curl -X POST http://localhost:8000/api/documents/DOCUMENT_ID/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the gross shipment weight?","top_k":5}'
```

The response includes the generated answer and the retrieved source chunks:

```json
{
  "document_id": "...",
  "question": "What is the gross shipment weight?",
  "answer": "The gross shipment weight is 2500 kg [1].",
  "citations": [
    {
      "chunk_id": "...:p0002:c0000",
      "page_number": 2,
      "text": "Gross shipment weight: 2500 kg",
      "relevance_score": 0.91
    }
  ],
  "llm_provider": "mock",
  "used_fallback": true
}
```

### LLM modes

`LOGIPRO_LLM_MODE` supports:

- `auto` (default): try Ollama, then use the grounded mock fallback if Ollama is
  unavailable or returns an invalid response.
- `mock`: skip Ollama and immediately return an extractive answer from the most
  relevant source chunks. This is the fastest reviewer setup.
- `ollama`: require Ollama and return `503 Service Unavailable` if it cannot be
  reached.

To force immediate fallback mode:

```bash
LOGIPRO_LLM_MODE=mock docker compose up --build
```

To use Ollama, run it on the host and install the configured model, for example:

```bash
ollama pull llama3.2
ollama serve
docker compose up --build
```

Compose points the application at `http://host.docker.internal:11434`. For local
Python development outside Docker, the default is `http://localhost:11434`.

## Run with Docker

```bash
docker compose up --build
```

Then visit:

- Browser interface: <http://localhost:8000/>
- API metadata: <http://localhost:8000/api/info>
- Health check: <http://localhost:8000/api/health>
- Swagger UI: <http://localhost:8000/docs>

Stop the application with:

```bash
docker compose down
```

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

## Project structure

```text
app/
  api/            # Thin route handlers and dependency providers
  core/           # Environment-driven configuration
  models/          # Internal document domain types
  repositories/   # SQLite persistence adapters
  schemas/        # Pydantic request and response models
  services/       # Upload, extraction, chunking, embedding, vector, and RAG services
frontend/         # Same-origin HTML, CSS, and JavaScript interface
data/
  uploads/        # Uploaded source documents
  chroma/         # Persistent ChromaDB data
tests/            # API smoke and contract tests
compose.yaml
Dockerfile
```

## API contracts

- `POST /api/documents/upload`
- `GET /api/documents/{document_id}/status`
- `POST /api/documents/{document_id}/query`

Configuration is read from environment variables prefixed with `LOGIPRO_`. For
example, `LOGIPRO_DATA_DIR=/app/data` selects the container's persistent data
directory.

Useful ingestion settings include:

| Variable | Default |
| --- | --- |
| `LOGIPRO_OCR_LANGUAGE` | `eng` |
| `LOGIPRO_OCR_TIMEOUT_SECONDS` | `60` |
| `LOGIPRO_OCR_PDF_DPI` | `200` |
| `LOGIPRO_OCR_FALLBACK_MIN_CHARACTERS` | `20` |
| `LOGIPRO_TEXT_CHUNK_SIZE` | `500` |
| `LOGIPRO_TEXT_CHUNK_OVERLAP` | `50` |
| `LOGIPRO_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `LOGIPRO_EMBEDDING_DEVICE` | `cpu` |
| `LOGIPRO_EMBEDDING_BATCH_SIZE` | `32` |
| `LOGIPRO_CHROMA_COLLECTION_NAME` | `logipro_document_chunks` |
| `LOGIPRO_CHROMA_BATCH_SIZE` | `100` |
| `LOGIPRO_LLM_MODE` | `auto` |
| `LOGIPRO_OLLAMA_BASE_URL` | `http://localhost:11434` |
| `LOGIPRO_OLLAMA_MODEL` | `llama3.2` |
| `LOGIPRO_OLLAMA_CONNECT_TIMEOUT_SECONDS` | `1` |
| `LOGIPRO_OLLAMA_RESPONSE_TIMEOUT_SECONDS` | `120` |
| `LOGIPRO_OLLAMA_TEMPERATURE` | `0.1` |
| `LOGIPRO_OLLAMA_MAX_TOKENS` | `512` |

The supplied image installs Tesseract's English language data. To use another
`LOGIPRO_OCR_LANGUAGE`, add its Debian Tesseract language package to the
`Dockerfile`.

> **Prototype limitation:** FastAPI background tasks execute in the API process
> after the response. They are not a durable job queue. Restarting the container
> during ingestion can leave a document in `PROCESSING`; a production deployment
> should add stale-job recovery or a durable worker queue.