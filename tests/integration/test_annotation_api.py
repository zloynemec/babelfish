from collections.abc import Mapping
from typing import Any

import anyio
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
    assert set(response.json()) == {"annotation", "annotator", "metadata"}
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
        {"text": "Something", "annotator": " \t "},
    ],
)
async def test_invalid_request(payload: Mapping[str, str | None]) -> None:
    transport = httpx.ASGITransport(app=_app(FakeAnnotator()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url", ["not a url", "https:///article", "https://example.org:bad", "http://[::1"]
)
async def test_malformed_url_is_rejected_before_fetch(url: str) -> None:
    fetcher = FakeFetcher("Article", content_type="text/plain")
    transport = httpx.ASGITransport(app=_app(FakeAnnotator(), fetcher=fetcher))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json={"url": url})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert fetcher.last_url is None


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["file:///article", "https://user:pass@example.org/article"])
async def test_disallowed_url_retains_403(url: str) -> None:
    transport = httpx.ASGITransport(app=_app(FakeAnnotator()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json={"url": url})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "url_not_allowed"


@pytest.mark.anyio
async def test_page_fetch_timeout_releases_worker_before_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_request(request: httpx.Request) -> httpx.Response:
        await anyio.sleep(1)
        raise AssertionError("the request should have been cancelled")

    monkeypatch.setattr(
        httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(slow_request)
    )
    settings = Settings(
        default_annotator="fake",
        annotation_fetch_timeout_seconds=0.2,
        annotation_timeout_seconds=0.6,
        max_concurrent_operations=1,
    )
    fake = FakeAnnotator()
    transport = httpx.ASGITransport(app=_app(fake, settings=settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        fetch = await client.post("/v1/annotate", json={"url": "https://8.8.8.8/article"})
        assert fake.last_request is None
        next_request = await client.post("/v1/annotate", json={"text": "Material"})

    assert fetch.status_code == 502
    assert fetch.json()["error"]["code"] == "content_fetch_failed"
    assert next_request.status_code == 200


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
            "/v1/annotate", json={"text": "Something", "annotator": " second "}
        )
        default = await client.post("/v1/annotate", json={"text": "Something", "annotator": None})
        listed = await client.get("/v1/annotators")
    assert response.status_code == 200
    assert response.json()["annotator"] == "second"
    assert default.status_code == 200
    assert default.json()["annotator"] == "fake"
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
@pytest.mark.parametrize(
    ("annotation", "status"),
    [
        ("Цена 105 тыс. рублей. Продажи выросли.", 200),
        ("Dr. Lee spoke. The team listened. The vote passed.", 200),
        ("Dr. Lee spoke.", 502),
    ],
)
async def test_abbreviation_does_not_count_as_sentence_end(annotation: str, status: int) -> None:
    class AbbreviationAnnotator(FakeAnnotator):
        def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
            return ProviderAnnotationResult(annotation=annotation)

    transport = httpx.ASGITransport(app=_app(AbbreviationAnnotator()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/annotate", json={"text": "Some text"})
    assert response.status_code == status
    if status == 200:
        assert response.json()["annotation"] == annotation
    else:
        assert response.json()["error"]["code"] == "annotation_failed"


class CopyingQwen(FakeAnnotator):
    name = "qwen_local"

    def __init__(self, *, always_copy: bool = False) -> None:
        super().__init__()
        self.requests: list[ProviderAnnotationRequest] = []
        self.always_copy = always_copy

    def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        self.requests.append(request)
        return ProviderAnnotationResult(
            annotation=request.text
            if self.always_copy or len(self.requests) == 1
            else "Представитель призвал прекратить войну. Общество желает мира."
        )


@pytest.mark.anyio
@pytest.mark.parametrize("always_copy", [False, True])
async def test_qwen_copy_is_retried_once_and_not_returned(always_copy: bool) -> None:
    provider = CopyingQwen(always_copy=always_copy)
    source = " ".join(f"слово{i}" for i in range(45)) + ". Второе предложение."
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(provider)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/annotate", json={"text": source, "annotator": "qwen_local"}
        )
    assert response.status_code == (502 if always_copy else 200)
    assert len(provider.requests) == 2
    assert provider.requests[0].format_violation is None
    assert "at most 25 words" in provider.requests[1].format_violation
    if always_copy:
        assert response.json()["error"]["code"] == "annotation_failed"
    else:
        assert response.json()["annotation"] != source


@pytest.mark.anyio
async def test_qwen_near_copy_within_word_limit_is_retried() -> None:
    provider = CopyingQwen()
    words = [f"word{i}" for i in range(30)]

    def annotate(request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        provider.requests.append(request)
        return ProviderAnnotationResult(
            annotation=" ".join(words[:10]) + ". " + " ".join(words[10:25]) + "."
            if len(provider.requests) == 1
            else "The representative called for peace. People want peace."
        )

    provider.annotate = annotate
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(provider)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/annotate", json={"text": " ".join(words), "annotator": "qwen_local"}
        )
    assert response.status_code == 200
    assert len(provider.requests) == 2
    assert "copies the source" in provider.requests[1].format_violation


@pytest.mark.anyio
async def test_qwen_timeout_does_not_start_paraphrase_retry() -> None:
    import time

    import anyio

    provider = CopyingQwen(always_copy=True)
    original = provider.annotate

    def annotate(request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        time.sleep(0.05)
        return original(request)

    provider.annotate = annotate
    settings = Settings(default_annotator="qwen_local", annotation_timeout_seconds=0.01)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(provider, settings=settings)), base_url="http://test"
    ) as client:
        response = await client.post("/v1/annotate", json={"text": " ".join(["word"] * 45)})
        assert response.status_code == 504
        await anyio.sleep(0.1)
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_qwen_mixed_word_is_retried_even_in_short_summary() -> None:
    provider = CopyingQwen()

    def annotate(request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        provider.requests.append(request)
        return ProviderAnnotationResult(
            annotation="Представитель хочет мирного разResolutionа. Люди хотят мира."  # noqa: RUF001
            if len(provider.requests) == 1
            else "Представитель призывает к миру. Люди хотят мира."
        )

    provider.annotate = annotate
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(provider)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/annotate", json={"text": "Люди хотят мира.", "annotator": "qwen_local"}
        )
    assert response.status_code == 200
    assert len(provider.requests) == 2
    assert "mixes Latin and Cyrillic" in provider.requests[1].format_violation
