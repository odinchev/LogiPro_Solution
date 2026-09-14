"""Digital text extraction with page-level Tesseract OCR fallback."""

import logging
import re
from pathlib import Path
from threading import Lock

from PIL import Image, ImageSequence
from pypdf import PdfReader

from app.models.ingestion import ExtractedPage

logger = logging.getLogger(__name__)


class TextExtractionService:
    """Extract page-aware text from supported PDF and image documents."""

    def __init__(
        self,
        *,
        ocr_language: str,
        ocr_timeout_seconds: float,
        pdf_dpi: int,
        fallback_min_characters: int,
    ) -> None:
        self._ocr_language = ocr_language
        self._ocr_timeout_seconds = ocr_timeout_seconds
        self._pdf_render_scale = pdf_dpi / 72
        self._fallback_min_characters = fallback_min_characters
        self._pdfium_lock = Lock()

    def extract(self, document_path: Path) -> list[ExtractedPage]:
        """Extract text while preserving one-based page or frame numbers."""
        if document_path.suffix.lower() == ".pdf":
            return self._extract_pdf(document_path)
        return self._extract_image(document_path)

    def _extract_pdf(self, document_path: Path) -> list[ExtractedPage]:
        extracted_pages: list[ExtractedPage] = []
        with document_path.open("rb") as pdf_stream:
            reader = PdfReader(pdf_stream)
            for page_index, page in enumerate(reader.pages):
                try:
                    digital_text = self._normalize_text(page.extract_text() or "")
                except Exception:
                    logger.warning(
                        "Digital text extraction failed for page %s of %s; using OCR",
                        page_index + 1,
                        document_path,
                        exc_info=True,
                    )
                    digital_text = ""
                if (
                    self._usable_character_count(digital_text)
                    >= self._fallback_min_characters
                ):
                    text = digital_text
                    method = "pypdf"
                else:
                    ocr_text = self._normalize_text(
                        self._ocr_pdf_page(document_path, page_index)
                    )
                    text = ocr_text or digital_text
                    method = "tesseract" if ocr_text else "pypdf"

                extracted_pages.append(
                    ExtractedPage(
                        page_number=page_index + 1,
                        text=text,
                        extraction_method=method,
                    )
                )

        return extracted_pages

    def _extract_image(self, document_path: Path) -> list[ExtractedPage]:
        extracted_pages: list[ExtractedPage] = []
        with Image.open(document_path) as image:
            for page_number, frame in enumerate(ImageSequence.Iterator(image), start=1):
                with frame.copy() as frame_image:
                    text = self._normalize_text(self._ocr_image(frame_image))
                extracted_pages.append(
                    ExtractedPage(
                        page_number=page_number,
                        text=text,
                        extraction_method="tesseract",
                    )
                )
        return extracted_pages

    def _ocr_pdf_page(self, document_path: Path, page_index: int) -> str:
        import pypdfium2 as pdfium

        with self._pdfium_lock:
            pdf_document = pdfium.PdfDocument(str(document_path))
            try:
                page = pdf_document[page_index]
                try:
                    bitmap = page.render(scale=self._pdf_render_scale)
                    try:
                        with bitmap.to_pil() as image:
                            return self._ocr_image(image)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                pdf_document.close()

    def _ocr_image(self, image: Image.Image) -> str:
        import pytesseract

        return pytesseract.image_to_string(
            image,
            lang=self._ocr_language,
            timeout=self._ocr_timeout_seconds,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        # Remove null bytes and standardize carriage returns
        cleaned = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        # Replace non-breaking spaces and tabs with regular spaces
        cleaned = cleaned.replace("\u00a0", " ").replace("\t", " ")
        # Split into paragraphs separated by two or more newlines
        paragraphs = re.split(r"\n{2,}", cleaned)
        normalized_paragraphs: list[str] = []
        for para in paragraphs:
            # Connect hyphenated line-breaks (e.g. "inter-\nnational" -> "international")
            para = re.sub(r"(\b\w+)-\n+(\w+\b)", r"\1\2", para)
            # Collapse single newlines within a paragraph into a space
            para = re.sub(r"\n+", " ", para)
            # Collapse multiple horizontal whitespace characters into a single space
            para = re.sub(r"[^\S\n]+", " ", para).strip()
            if para:
                normalized_paragraphs.append(para)
        return "\n\n".join(normalized_paragraphs)

    @staticmethod
    def _usable_character_count(text: str) -> int:
        return sum(not character.isspace() for character in text)