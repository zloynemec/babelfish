import json
from collections.abc import AsyncIterator

import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/v1/translate", "/v1/annotate"])
@pytest.mark.parametrize("chunked", [False, True])
async def test_body_limit_rejects_before_json_validation(path: str, chunked: bool) -> None:
    provider = FakeTranslatorProvider()
    registry = TranslatorRegistry()
    registry.register(provider)
    app = create_app(settings=Settings(max_request_body_bytes=64), registry=registry)
    chunks_read = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal chunks_read
        for _ in range(100):
            chunks_read += 1
            yield b"x" * 40

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(path, content=chunks() if chunked else b"x" * 80)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert chunks_read == (2 if chunked else 0)
    assert provider.last_request is None


@pytest.mark.anyio
async def test_body_limit_accepts_exact_boundary_and_checks_actual_bytes() -> None:
    body = json.dumps({"text": "Hello", "target_language": "ru"}).encode()
    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider())
    app = create_app(
        settings=Settings(default_translator="fake", max_request_body_bytes=len(body)),
        registry=registry,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/v1/translate", content=body, headers={"Content-Type": "application/json"}
        )
        rejected = await client.post(
            "/v1/translate",
            content=body + b" ",
            headers={"Content-Length": "1", "Content-Type": "application/json"},
        )
    assert accepted.status_code == 200
    assert rejected.status_code == 413


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/v1/translate", {"text": "x" * 100, "target_language": "ru"}),
        (
            "/v1/translate",
            {"text": "x", "target_language": "ru", "translator_params": {"a": "x" * 100}},
        ),
        ("/v1/annotate", {"text": "x", "annotator_params": {"a": "x" * 100}}),
        ("/v1/annotate", {"text": "x", "unknown": "x" * 100}),
    ],
)
async def test_body_limit_covers_text_params_and_unknown_fields(path: str, payload: dict) -> None:
    app = create_app(settings=Settings(max_request_body_bytes=64))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(path, json=payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
