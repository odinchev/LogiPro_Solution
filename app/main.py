"""FastAPI application factory and process entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.repositories.sqlite_document_repository import SQLiteDocumentRepository
from app.schemas.common import ServiceInfoResponse
from app.services.answer_generation_service import OllamaAnswerGenerator
from app.services.document_ingestion_service import (
    DocumentIngestionService,
    DocumentProcessor,
)
from app.services.document_service import DocumentService
from app.services.embedding_service import SentenceTransformerEmbeddingService
from app.services.exceptions import (
    DocumentNotFoundError,
    DocumentNotReadyError,
    InvalidUploadError,
    LlmUnavailableError,
    RelevantContextNotFoundError,
    UnsupportedDocumentTypeError,
)
from app.services.rag_service import RagService
from app.services.text_chunking_service import TextChunkingService
from app.services.text_extraction_service import TextExtractionService
from app.services.vector_store_service import ChromaVectorStore


def create_app(
    settings: Settings | None = None,
    document_processor: DocumentProcessor | None = None,
    rag_service: RagService | None = None,
) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    document_repository = SQLiteDocumentRepository(settings.sqlite_path)
    document_service = DocumentService(document_repository, settings.upload_dir)
    embedding_service = SentenceTransformerEmbeddingService(
        model_name=settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )
    vector_store = ChromaVectorStore(
        persist_directory=settings.chroma_dir,
        collection_name=settings.chroma_collection_name,
        batch_size=settings.chroma_batch_size,
    )
    if document_processor is None:
        document_processor = DocumentIngestionService(
            repository=document_repository,
            text_extractor=TextExtractionService(
                ocr_language=settings.ocr_language,
                ocr_timeout_seconds=settings.ocr_timeout_seconds,
                pdf_dpi=settings.ocr_pdf_dpi,
                fallback_min_characters=settings.ocr_fallback_min_characters,
            ),
            text_chunker=TextChunkingService(
                chunk_size=settings.text_chunk_size,
                chunk_overlap=settings.text_chunk_overlap,
            ),
            embedding_service=embedding_service,
            vector_store=vector_store,
        )
    if rag_service is None:
        rag_service = RagService(
            repository=document_repository,
            embedding_service=embedding_service,
            vector_store=vector_store,
            answer_generator=OllamaAnswerGenerator(
                mode=settings.llm_mode,
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                connect_timeout_seconds=settings.ollama_connect_timeout_seconds,
                response_timeout_seconds=settings.ollama_response_timeout_seconds,
                temperature=settings.ollama_temperature,
                max_tokens=settings.ollama_max_tokens,
            ),
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Prepare local storage and initialize the SQLite schema."""
        del application
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        document_repository.initialize()
        yield

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Local-first shipping document extraction and Q&A API.",
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.document_repository = document_repository
    application.state.document_service = document_service
    application.state.document_processor = document_processor
    application.state.rag_service = rag_service
    application.mount(
        "/assets",
        StaticFiles(directory=frontend_dir),
        name="frontend-assets",
    )

    @application.exception_handler(InvalidUploadError)
    async def invalid_upload_handler(
        request: Request,
        exc: InvalidUploadError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )

    @application.exception_handler(UnsupportedDocumentTypeError)
    async def unsupported_document_type_handler(
        request: Request,
        exc: UnsupportedDocumentTypeError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={"detail": str(exc)},
        )

    @application.exception_handler(DocumentNotFoundError)
    async def document_not_found_handler(
        request: Request,
        exc: DocumentNotFoundError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )

    @application.exception_handler(DocumentNotReadyError)
    async def document_not_ready_handler(
        request: Request,
        exc: DocumentNotReadyError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc), "document_status": exc.status.value},
        )

    @application.exception_handler(RelevantContextNotFoundError)
    @application.exception_handler(LlmUnavailableError)
    async def query_dependency_unavailable_handler(
        request: Request,
        exc: RelevantContextNotFoundError | LlmUnavailableError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    @application.get("/", response_class=FileResponse, include_in_schema=False)
    async def frontend() -> FileResponse:
        """Serve the document intelligence browser interface."""
        return FileResponse(frontend_dir / "index.html")

    @application.get(
        f"{settings.api_prefix}/info",
        response_model=ServiceInfoResponse,
        tags=["Service"],
    )
    async def service_info() -> ServiceInfoResponse:
        """Return basic service and API-documentation information."""
        return ServiceInfoResponse(
            name=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
            docs_url="/docs",
        )

    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()