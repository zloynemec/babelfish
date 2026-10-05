import json
import socket

import httpx
import pytest

from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotatorUnavailableError,
    UrlNotAllowedError,
)
from translation_service.domain.annotation import ProviderAnnotationRequest
from translation_service.providers.iishko import IishkoProvider
from translation_service.providers.qwen_local import QwenLocalProvider
from translation_service.services.content import SafePageFetcher, extract_html_text


def test_html_extraction_skips_service_content() -> None:
    html = (
        "<style>body{color:red}</style><nav>Menu</nav><main>"
        "<h1>Title</h1><p>Actual content.</p><script>alert(1)</script></main><footer>End</footer>"
    )
    assert extract_html_text(html) == "Title\nActual content."


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:pass@example.org/"])
def test_fetcher_rejects_unsafe_url_before_dns(url: str) -> None:
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100)
    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch(url)


def test_fetcher_rejects_private_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 80))],
    )
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100)
    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch("http://example.org/")


def test_explicit_dns_does_not_allow_private_ip_literal() -> None:
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100, dns_server="1.1.1.1")
    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch("http://127.0.0.1/")


def test_iishko_uses_configured_model_and_does_not_expose_key() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Первое. Второе."}}]})

    provider = IishkoProvider(
        api_key="test-secret",
        base_url="https://api.reformboss.com/v1",
        model="qwen3.8-flash",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    result = provider.annotate(ProviderAnnotationRequest(text="Input text", params={}))
    assert result.annotation == "Первое. Второе."
    assert captured[0].url.path == "/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer test-secret"
    body = json.loads(captured[0].content)
    assert body["model"] == "qwen3.8-flash"
    assert body["enable_thinking"] is False
    assert body["messages"][1]["content"] == "Input text"


@pytest.mark.parametrize(
    ("status, payload, error_type"),
    [
        (429, {"error": "secret"}, AnnotatorUnavailableError),
        (400, {"error": {"code": "Arrearage"}}, AnnotatorUnavailableError),
        (200, {"choices": []}, AnnotationFailedError),
    ],
)
def test_iishko_normalizes_upstream_errors(
    status: int, payload: dict[str, object], error_type: type[Exception]
) -> None:
    provider = IishkoProvider(
        api_key="test-secret",
        base_url="https://api.reformboss.com/v1",
        model="qwen3.8-flash",
        timeout_seconds=1,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
    )
    with pytest.raises(error_type) as caught:
        provider.annotate(ProviderAnnotationRequest(text="private", params={}))
    assert "secret" not in str(caught.value)
    assert "private" not in str(caught.value)


def test_qwen_local_uses_same_prompt_and_local_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Первое. Второе."}}]})

    provider = QwenLocalProvider(
        base_url="http://127.0.0.1:8081/v1",
        model="qwen3-4b",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    assert provider.health().ready is True
    result = provider.annotate(ProviderAnnotationRequest(text="Source text", params={}))
    assert result.annotation == "Первое. Второе."
    assert captured[1].url.path == "/v1/chat/completions"
    body = json.loads(captured[1].content)
    assert body["model"] == "qwen3-4b"
    assert body["messages"][1]["content"] == "Source text"


def test_qwen_local_reports_unavailable_when_server_is_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    provider = QwenLocalProvider(
        base_url="http://127.0.0.1:8081/v1",
        model="qwen3-4b",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    assert provider.health().ready is False
    with pytest.raises(AnnotatorUnavailableError):
        provider.annotate(ProviderAnnotationRequest(text="Source text", params={}))
