"""Tests for digital extraction and OCR fallback selection."""

from pathlib import Path

from PIL import Image

from app.services.text_extraction_service import TextExtractionService


class FakePdfPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class BrokenPdfPage:
    def extract_text(self) -> str:
        raise RuntimeError("invalid content stream")


class FakePdfReader:
    def __init__(self, pages: list[FakePdfPage]) -> None:
        self.pages = pages


def build_service() -> TextExtractionService:
    return TextExtractionService(
        ocr_language="eng",
        ocr_timeout_seconds=10,
        pdf_dpi=200,
        fallback_min_characters=10,
    )


def test_pdf_uses_digital_text_and_ocrs_only_sparse_pages(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = build_service()
    pdf_path = tmp_path / "shipment.pdf"
    pdf_path.write_bytes(b"placeholder")
    monkeypatch.setattr(
        "app.services.text_extraction_service.PdfReader",
        lambda _: FakePdfReader(
            [
                FakePdfPage("Digitally extracted shipping text"),
                FakePdfPage("   "),
            ]
        ),
    )
    ocr_calls: list[int] = []

    def fake_ocr_pdf_page(_: Path, page_index: int) -> str:
        ocr_calls.append(page_index)
        return "Scanned page text"

    monkeypatch.setattr(service, "_ocr_pdf_page", fake_ocr_pdf_page)

    pages = service.extract(pdf_path)

    assert [(page.page_number, page.text, page.extraction_method) for page in pages] == [
        (1, "Digitally extracted shipping text", "pypdf"),
        (2, "Scanned page text", "tesseract"),
    ]
    assert ocr_calls == [1]


def test_pdf_page_extraction_error_falls_back_to_ocr(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = build_service()
    pdf_path = tmp_path / "broken-page.pdf"
    pdf_path.write_bytes(b"placeholder")
    monkeypatch.setattr(
        "app.services.text_extraction_service.PdfReader",
        lambda _: FakePdfReader([BrokenPdfPage()]),
    )
    monkeypatch.setattr(
        service,
        "_ocr_pdf_page",
        lambda _path, _page_index: "Recovered by OCR",
    )

    pages = service.extract(pdf_path)

    assert pages[0].text == "Recovered by OCR"
    assert pages[0].extraction_method == "tesseract"


def test_multiframe_image_uses_ocr_and_retains_frame_numbers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "multipage.tiff"
    first = Image.new("RGB", (5, 5), "white")
    second = Image.new("RGB", (5, 5), "black")
    first.save(image_path, save_all=True, append_images=[second])
    service = build_service()
    responses = iter(["first frame", "second frame"])
    monkeypatch.setattr(service, "_ocr_image", lambda _: next(responses))

    pages = service.extract(image_path)

    assert [(page.page_number, page.text) for page in pages] == [
        (1, "first frame"),
        (2, "second frame"),
    ]
    assert all(page.extraction_method == "tesseract" for page in pages)