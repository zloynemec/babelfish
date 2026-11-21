import json

import httpx
import pytest
from fastapi import FastAPI

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.iishko import IishkoProvider
from translation_service.providers.qwen_local import QwenLocalProvider
from translation_service.services import extraction
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.content import SafePageFetcher
from translation_service.services.extraction import ContentService

HTML = (
    "<nav>Menu</nav><article><header><h1>Library schedule</h1></header>"
    "<p>We are open on weekdays.</p><div>Accept cookies</div>"
    "<table><tr><td>Monday</td><td>09:00-18:00</td></tr></table>"
    "<script>Hidden script</script></article><footer>Privacy policy</footer>"
)
CONTENT = "Library schedule\nWe are open on weekdays.\nMonday 09:00-18:00"


class FixtureFetcher(SafePageFetcher):
    def fetch(self, url: str) -> tuple[str, str]:
        assert url == "https://example.org/library"
        return HTML, "text/html"


def content_app(
    provider_name: str,
    completion: str,
    *,
    finish_reason: str = "stop",
    requests: list[dict[str, object]],
    fetcher: SafePageFetcher | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        assert request.url.path == "/v1/chat/completions"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": finish_reason, "message": {"content": completion}}]
            },
        )

    registry = AnnotatorRegistry()
    transport = httpx.MockTransport(upstream)
    if provider_name == "iishko":
        registry.register(
            IishkoProvider(
                api_key="test-key",
                base_url="https://iishko.test/v1",
                model="test-model",
                timeout_seconds=1,
                transport=transport,
            )
        )
    else:
        registry.register(
            QwenLocalProvider(
                base_url="http://qwen.test/v1",
                model="test-model",
                timeout_seconds=1,
                transport=transport,
            )
        )
    config = settings or Settings(default_annotator=provider_name)
    app = create_app(settings=config, annotator_registry=registry)
    app.state.content_service = ContentService(
        registry, config, fetcher=fetcher, workers=app.state.workers
    )
    return app


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("iishko", {"html": HTML}),
        ("qwen_local", {"url": "https://example.org/library", "annotator": "qwen_local"}),
        (
            "iishko",
            {
                "text": "Library schedule\nWe are open on weekdays.\n"
                "Accept cookies\nMonday 09:00-18:00"
            },
        ),
    ],
)
async def test_content_returns_selected_original_blocks(
    provider: str, payload: dict[str, str]
) -> None:
    requests: list[dict[str, object]] = []
    app = content_app(
        provider,
        '{"discard":[3]}',
        requests=requests,
        fetcher=FixtureFetcher(timeout_seconds=1, max_bytes=32_000),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/content", json={**payload, "annotator_params": {"model": "override"}}
        )

    assert response.status_code == 200
    result = response.json()
    assert set(result) == {"content", "annotator", "metadata"}
    assert result["content"] == CONTENT
    assert result["annotator"] == provider
    assert result["metadata"]["duration_ms"] >= 0
    assert result["metadata"]["truncated"] is False
    [completion] = requests
    assert completion["model"] == "override"
    messages = completion["messages"]
    assert isinstance(messages, list)
    assert messages[1] == {
        "role": "user",
        "content": "1: Library schedule\n2: We are open on weekdays.\n"
        "3: Accept cookies\n4: Monday 09:00-18:00",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("completion", "finish_reason", "status", "code"),
    [
        ('{"discard":[1]}', "stop", 422, "content_not_extractable"),
        ("The page contains a schedule.", "stop", 502, "content_extraction_failed"),
        ('{"discard":[true]}', "stop", 502, "content_extraction_failed"),
        ('{"discard":[2]}', "stop", 502, "content_extraction_failed"),
        ('{"discard":[]}', "length", 502, "content_extraction_failed"),
    ],
)
async def test_content_rejects_unusable_selection(
    completion: str, finish_reason: str, status: int, code: str
) -> None:
    app = content_app("iishko", completion, finish_reason=finish_reason, requests=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/content", json={"text": "Library schedule"})

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.anyio
async def test_content_reuses_annotation_input_and_fetch_rules() -> None:
    requests: list[dict[str, object]] = []
    app = content_app("iishko", '{"discard":[]}', requests=requests)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        mixed = await client.post("/v1/content", json={"text": "Text", "html": "<p>Text</p>"})
        forbidden = await client.post("/v1/content", json={"url": "file:///tmp/page.html"})

    assert mixed.status_code == 400
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "url_not_allowed"
    assert not requests


@pytest.mark.anyio
async def test_content_processes_the_whole_article_across_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extraction, "_CONTENT_BATCH_CHARS", 50)
    requests: list[dict[str, object]] = []
    config = Settings(default_annotator="iishko", annotation_max_text_chars=12)
    article = (
        "Opening paragraph.\n"
        "This long paragraph contains facts from multiple parts of the source article.\n"
        "Final section.\nThe last useful fact."
    )
    app = content_app("iishko", '{"discard":[]}', requests=requests, settings=config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        plain = await client.post("/v1/content", json={"text": article})
        html = await client.post(
            "/v1/content", json={"html": "<p>" + "</p><p>".join(article.splitlines()) + "</p>"}
        )

    for response in (plain, html):
        assert response.status_code == 200
        assert response.json()["content"] == article
        assert response.json()["metadata"]["truncated"] is False
    assert len(requests) > 2
    assert "The last useful fact." in str(requests[-1]["messages"])
