import json
import logging
from threading import Event

import anyio
import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "status", "result"),
    [
        ("success", 200, "success"),
        ("unavailable", 503, "translator_unavailable"),
        ("timeout", 504, "translation_timeout"),
        ("failure", 500, "translation_failed"),
        ("unexpected", 500, "translation_failed"),
        ("validation", 400, "invalid_request"),
        ("body_limit", 413, "request_body_too_large"),
    ],
)
async def test_request_logs_safe_metadata(
    case: str, status: int, result: str, caplog: pytest.LogCaptureFixture
) -> None:
    release = Event()
    secret = "PRIVATE-TEXT-DO-NOT-LOG"

    def translate(request) -> str:
        if case == "timeout":
            assert release.wait(2)
        if case == "failure":
            raise RuntimeError(secret)
        return secret

    registry = TranslatorRegistry()
    registry.register(
        FakeTranslatorProvider(ready=case != "unavailable", translate_function=translate)
    )
    app = create_app(
        settings=Settings(
            default_translator="fake",
            translation_timeout_seconds=0.05,
            max_concurrent_operations=1,
            max_request_body_bytes=32 if case == "body_limit" else 1000,
        ),
        registry=registry,
    )

    @app.get("/internal-error")
    async def fail() -> None:
        raise RuntimeError(secret)

    payload = {"text": secret, "target_language": "ru"}
    if case == "validation":
        payload.pop("target_language")
    caplog.set_level(logging.INFO, logger="uvicorn.error.translation_service")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            if case == "unexpected":
                response = await client.get(f"/internal-error?token={secret}")
            else:
                response = await client.post(f"/v1/translate?token={secret}", json=payload)
        finally:
            release.set()
            with anyio.fail_after(2):
                await app.state.workers.run(lambda: None)
    assert response.status_code == status
    records = [
        record for record in caplog.records if record.name == "uvicorn.error.translation_service"
    ]
    assert len(records) == 1
    entry = json.loads(records[0].getMessage())
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert entry["status_code"] == status
    assert entry["result"] == result
    assert entry["duration_ms"] >= 0
    assert secret not in records[0].getMessage()
    if case not in ("validation", "body_limit", "unexpected"):
        assert entry["translator"] == "fake"
        assert entry["source_language"] == "en"
        assert entry["target_language"] == "ru"
        assert entry["text_length"] == len(secret)
