"""Environment-driven application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from ``LOGIPRO_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="LOGIPRO_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LogiPro Document Intelligence Service"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api"
    data_dir: Path = Path("data")
    ocr_language: str = "eng"
    ocr_timeout_seconds: float = Field(default=60.0, gt=0)
    ocr_pdf_dpi: int = Field(default=200, ge=72, le=600)
    ocr_fallback_min_characters: int = Field(default=20, ge=0)
    text_chunk_size: int = Field(default=500, ge=1)
    text_chunk_overlap: int = Field(default=50, ge=0)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    embedding_batch_size: int = Field(default=32, ge=1)
    chroma_collection_name: str = "logipro_document_chunks"
    chroma_batch_size: int = Field(default=100, ge=1)
    llm_mode: Literal["auto", "ollama", "mock"] = "auto"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_connect_timeout_seconds: float = Field(default=1.0, gt=0)
    ollama_response_timeout_seconds: float = Field(default=120.0, gt=0)
    ollama_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    ollama_max_tokens: int = Field(default=512, ge=1)

    @property
    def upload_dir(self) -> Path:
        """Directory where source documents will be stored."""
        return self.data_dir / "uploads"

    @property
    def sqlite_path(self) -> Path:
        """Path to the SQLite metadata database."""
        return self.data_dir / "documents.sqlite3"

    @property
    def chroma_dir(self) -> Path:
        """Directory for the persistent ChromaDB store."""
        return self.data_dir / "chroma"

    @model_validator(mode="after")
    def validate_chunk_settings(self) -> "Settings":
        """Ensure chunk windows always make forward progress."""
        if self.text_chunk_overlap >= self.text_chunk_size:
            raise ValueError("text_chunk_overlap must be smaller than text_chunk_size")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance per process."""
    return Settings()