from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.core.errors import InvalidAnnotatorParamsError
from translation_service.domain.annotation import (
    AnnotatorHealth,
    ProviderAnnotationRequest,
    ProviderAnnotationResult,
)
from translation_service.main import create_app
from translation_service.services.annotation import AnnotationService
from translation_service.services.annotator_registry import AnnotatorRegistry


class FakeAnnotator:
    name = "fake"

    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.last_request: ProviderAnnotationRequest | None = None

    def health(self) -> AnnotatorHealth:
        return AnnotatorHealth(ready=self.ready)

    def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        self.last_request = request
        if request.params:
            raise InvalidAnnotatorParamsError()
        return ProviderAnnotationResult(annotation="Первое предложение. Второе предложение.")


class AbbreviationAnnotator(FakeAnnotator):
    def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        return ProviderAnnotationResult(annotation="Цена 105 тыс. рублей. Продажи выросли.")


class FakeFetcher:
    def __init__(self, body: str, content_type: str = "text/html") -> None:
        self.body = body
        self.content_type = content_type
        self.last_url: str | None = None

    def fetch(self, url: str) -> tuple[str, str]:
        self.last_url = url
        return self.body, self.content_type


def _app(
    fake: FakeAnnotator,
    *,
    fetcher: FakeFetcher | None = None,
    settings: Settings | None = None,
) -> Any:
    resolved_settings = settings or Settings(default_annotator="fake")
    registry = AnnotatorRegistry()
    registry.register(fake)
    return create_app(
        settings=resolved_settings,
        annotator_registry=registry,
        annotation_service=AnnotationService(registry, resolved_settings, fetcher),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("payload", "expected_text"),
    [
        ({"text": "Raw <b>input</b>"}, "Raw <b>input</b>"),
        ({"html": "<nav>Menu</nav><main><p>Main story.</p></main>"}, "Main story."),
        ({"url": "https://example.org/story"}, "Fetched article."),
    ],
)
async def test_three_input_modes(payload: dict[str, str], expected_text: str) -> None:
    fake = FakeAnnotator()
    fetcher = FakeFetcher("<script>evil()</script><article>Fetched article.</article>")
    transport = httpx.ASGITransport(app=_app(fake, fetcher=fetcher))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json=payload)

    assert response.status_code == 200
    assert response.json()["annotation"] == "Первое предложение. Второе предложение."
    assert response.json()["annotator"] == "fake"
    assert response.json()["language"] == "ru"
    assert response.json()["metadata"]["duration_ms"] >= 0
    assert fake.last_request is not None
    assert fake.last_request.text == expected_text
    if "url" in payload:
        assert fetcher.last_url == payload["url"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": "https://example.org", "text": "x"},
        {"url": None, "text": "x"},
        {"text": " "},
        {"html": ""},
    ],
)
async def test_invalid_input_selection(payload: Mapping[str, str | None]) -> None:
    transport = httpx.ASGITransport(app=_app(FakeAnnotator()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.anyio
async def test_annotator_selection_and_list() -> None:
    first = FakeAnnotator()
    second = FakeAnnotator()
    second.name = "SECOND"
    registry = AnnotatorRegistry()
    registry.register(first)
    registry.register(second)
    app = create_app(settings=Settings(default_annotator="fake"), annotator_registry=registry)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/annotate", json={"text": "Something", "annotator": "second"}
        )
        listed = await client.get("/v1/annotators")
    assert response.status_code == 200
    assert response.json()["annotator"] == "second"
    assert second.last_request is not None
    assert listed.json() == {
        "annotators": [{"name": "fake", "ready": True}, {"name": "second", "ready": True}],
        "default_annotator": "fake",
    }


@pytest.mark.anyio
async def test_unknown_unavailable_and_params_errors() -> None:
    fake = FakeAnnotator()
    app = _app(fake)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unknown = await client.post(
            "/v1/annotate", json={"text": "Something", "annotator": "missing"}
        )
        invalid_params = await client.post(
            "/v1/annotate", json={"text": "Something", "annotator_params": {"bad": 1}}
        )
        fake.ready = False
        unavailable = await client.post("/v1/annotate", json={"text": "Something"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "unknown_annotator"
    assert invalid_params.status_code == 422
    assert invalid_params.json()["error"]["code"] == "invalid_annotator_params"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "annotator_unavailable"


@pytest.mark.anyio
async def test_text_limit_is_not_silently_truncated() -> None:
    fake = FakeAnnotator()
    settings = Settings(default_annotator="fake", annotation_max_text_chars=5)
    transport = httpx.ASGITransport(app=_app(fake, settings=settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json={"text": "123456"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "content_too_large"
    assert fake.last_request is None


@pytest.mark.anyio
async def test_html_truncation_is_reported() -> None:
    fake = FakeAnnotator()
    settings = Settings(default_annotator="fake", annotation_max_text_chars=5)
    transport = httpx.ASGITransport(app=_app(fake, settings=settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json={"html": "<main>123456</main>"})
    assert response.status_code == 200
    assert response.json()["metadata"]["truncated"] is True
    assert fake.last_request is not None
    assert fake.last_request.text == "12345"


@pytest.mark.anyio
async def test_abbreviation_does_not_count_as_sentence_end() -> None:
    transport = httpx.ASGITransport(app=_app(AbbreviationAnnotator()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json={"text": "Some text"})
    assert response.status_code == 200
