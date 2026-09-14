"""Tests for Ollama generation and no-Ollama fallback behavior."""

import httpx
import pytest

from app.models.query import RetrievedChunk
from app.services.answer_generation_service import OllamaAnswerGenerator
from app.services.exceptions import LlmUnavailableError


def chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            id="document:p0002:c0000",
            text="Gross weight is 2500 kg.",
            page_number=2,
            filename="shipment.pdf",
            relevance_score=0.9,
        ),
        RetrievedChunk(
            id="document:p0003:c0000",
            text="Destination is Rotterdam.",
            page_number=3,
            filename="shipment.pdf",
            relevance_score=0.8,
        ),
    ]


def generator(mode: str = "auto") -> OllamaAnswerGenerator:
    return OllamaAnswerGenerator(
        mode=mode,
        base_url="http://ollama.test:11434",
        model="test-model",
        connect_timeout_seconds=0.1,
        response_timeout_seconds=1,
        temperature=0.1,
        max_tokens=128,
    )


def test_mock_mode_returns_grounded_excerpts_without_http(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.answer_generation_service.httpx.Client",
        lambda **_: (_ for _ in ()).throw(AssertionError("HTTP must not be called")),
    )

    result = generator("mock").generate(
        question="What is the gross weight?",
        chunks=chunks(),
    )

    assert result.provider == "mock"
    assert result.used_fallback is True
    assert "Gross weight is 2500 kg" in result.text
    assert "[1]" in result.text


def test_auto_mode_uses_mock_when_ollama_is_unavailable(monkeypatch) -> None:
    def unavailable(**_):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        "app.services.answer_generation_service.httpx.Client",
        unavailable,
    )

    result = generator("auto").generate(
        question="What is the gross weight?",
        chunks=chunks(),
    )

    assert result.provider == "mock"
    assert result.used_fallback is True


def test_required_ollama_mode_raises_when_unavailable(monkeypatch) -> None:
    def unavailable(**_):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        "app.services.answer_generation_service.httpx.Client",
        unavailable,
    )

    with pytest.raises(LlmUnavailableError):
        generator("ollama").generate(
            question="What is the gross weight?",
            chunks=chunks(),
        )


def test_ollama_success_uses_chat_api_and_numbered_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "message": {
                    "role": "assistant",
                    "content": "The gross weight is 2500 kg [1].",
                }
            }

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, path: str, *, json: dict[str, object]) -> FakeResponse:
            captured["path"] = path
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.answer_generation_service.httpx.Client",
        FakeClient,
    )

    result = generator("auto").generate(
        question="What is the gross weight?",
        chunks=chunks(),
    )

    assert result.text == "The gross weight is 2500 kg [1]."
    assert result.provider == "ollama:test-model"
    assert result.used_fallback is False
    assert captured["path"] == "/api/chat"
    payload = captured["payload"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.1, "num_predict": 128}
    user_content = payload["messages"][1]["content"]
    assert "[1] Page 2 (shipment.pdf)" in user_content
    assert "[2] Page 3 (shipment.pdf)" in user_content


def test_ollama_custom_model_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "message": {
                    "role": "assistant",
                    "content": "Custom model answer.",
                }
            }

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, path: str, *, json: dict[str, object]) -> FakeResponse:
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.answer_generation_service.httpx.Client",
        FakeClient,
    )

    result = generator("auto").generate(
        question="What is the cargo?",
        chunks=chunks(),
        model="mistral:7b",
    )

    assert result.provider == "ollama:mistral:7b"
    assert captured["payload"]["model"] == "mistral:7b"


def test_ollama_is_available_ping(monkeypatch) -> None:
    gen = generator("auto")

    class FakeResponseOk:
        is_success = True

    class FakeClientOk:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def get(self, path: str) -> FakeResponseOk:
            return FakeResponseOk()

    monkeypatch.setattr("app.services.answer_generation_service.httpx.Client", FakeClientOk)
    assert gen.is_available() is True

    class FakeClientFail:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def get(self, path: str):
            raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.answer_generation_service.httpx.Client", FakeClientFail)
    assert gen.is_available() is False