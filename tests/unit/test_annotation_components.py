import json
import socket
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import anyio
import dns.asyncresolver
import httpx
import pytest

from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotatorUnavailableError,
    ContentFetchFailedError,
    ContentTooLargeError,
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


def test_content_html_extraction_keeps_price_and_article_contact_details() -> None:
    html = (
        "<main><article><h1>Course enrollment</h1>"
        "<p>Tuition: <strong>25 €</strong><span>Materials are included.</span></p>"
        "<p>The <strong>in</strong><em>structor</em> can answer questions.</p>"
        "<section><p>Accessibility contact: access@example.org.</p>"
        '<form method="post"><input type="email"></form></section>'
        "</article><section><div><h2>Get weekly offers</h2><p>Sign up now.</p></div>"
        '<form method="POST"><input type="email"></form></section></main>'
    )
    assert extract_html_text(html, preserve_content_blocks=True) == (
        "Course enrollment\nTuition: 25 €\nMaterials are included.\n"
        "The instructor can answer questions.\nAccessibility contact: access@example.org."
    )


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:pass@example.org/"])
def test_fetcher_rejects_unsafe_url_before_dns(url: str) -> None:
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100)
    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch(url)


def test_fetcher_rejects_private_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = Mock()
    answers.addresses.return_value = ["8.8.8.8", "127.0.0.1"]
    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve_name", AsyncMock(return_value=answers))
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100)
    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch("http://example.org/")


def test_explicit_dns_does_not_allow_private_ip_literal() -> None:
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100, dns_server="1.1.1.1")
    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch("http://127.0.0.1/")


@pytest.mark.parametrize("dns_server", [None, "1.1.1.1"])
def test_page_deadline_cancels_dns(monkeypatch: pytest.MonkeyPatch, dns_server: str | None) -> None:
    cancelled = False

    async def slow_lookup(*args: object, **kwargs: object) -> None:
        nonlocal cancelled
        try:
            await anyio.sleep(1)
        except anyio.get_cancelled_exc_class():
            cancelled = True
            raise

    lookup = AsyncMock(side_effect=slow_lookup)
    resolver = Mock(resolve_name=lookup)
    resolver_factory = Mock(return_value=resolver)
    monkeypatch.setattr(dns.asyncresolver, "Resolver", resolver_factory)
    # Keep the old DNS paths offline too.
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=OSError))
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", Mock(side_effect=dns.resolver.NoAnswer))
    fetcher = SafePageFetcher(timeout_seconds=0.2, max_bytes=100, dns_server=dns_server)

    with pytest.raises(ContentFetchFailedError):
        fetcher.fetch("https://example.org/article")

    assert cancelled
    resolver_factory.assert_called_once_with(configure=dns_server is None)
    if dns_server is not None:
        assert resolver.nameservers == [dns_server]


def test_page_deadline_cancels_request_before_response_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = False

    async def slow_request(request: httpx.Request) -> httpx.Response:
        nonlocal cancelled
        try:
            await anyio.sleep(1)
        except anyio.get_cancelled_exc_class():
            cancelled = True
            raise
        raise AssertionError("the request should have been cancelled")

    monkeypatch.setattr(
        httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(slow_request)
    )
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=OSError))
    fetcher = SafePageFetcher(timeout_seconds=0.2, max_bytes=100)

    with pytest.raises(ContentFetchFailedError):
        fetcher.fetch("https://8.8.8.8/article")

    assert cancelled


def test_page_deadline_is_shared_across_redirects_and_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_hosts: list[str] = []
    read_chunks = 0
    closed = False

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal read_chunks
            for _ in range(4):
                await anyio.sleep(0.05)
                read_chunks += 1
                yield b"x"

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    async def respond(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.headers["host"])
        assert request.url.host == "8.8.8.8"
        assert request.extensions["sni_hostname"] == request.headers["host"]
        if len(requested_hosts) == 1:
            await anyio.sleep(0.15)
            return httpx.Response(302, headers={"Location": "https://example.com/article"})
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, stream=SlowBody())

    answers = Mock()
    answers.addresses.return_value = ["8.8.8.8"]
    lookup = AsyncMock(return_value=answers)
    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve_name", lookup)
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=OSError))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    fetcher = SafePageFetcher(timeout_seconds=0.30, max_bytes=100)

    with pytest.raises(ContentFetchFailedError):
        fetcher.fetch("https://example.org/story")

    assert requested_hosts == ["example.org", "example.com"]
    assert lookup.await_count == 2
    first, second = lookup.await_args_list
    assert second.kwargs["lifetime"] < first.kwargs["lifetime"]
    assert 1 <= read_chunks < 4
    assert closed


def test_page_redirect_rechecks_destination_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respond = Mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/article"})
    )
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=100)

    with pytest.raises(UrlNotAllowedError):
        fetcher.fetch("http://8.8.8.8/")

    respond.assert_called_once()


@pytest.mark.parametrize("max_bytes", [3, 4])
def test_page_stream_respects_byte_limit_and_charset(
    monkeypatch: pytest.MonkeyPatch, max_bytes: int
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain; charset=latin-1"},
            stream=httpx.ByteStream(b"caf\xe9"),
        )

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=OSError))
    fetcher = SafePageFetcher(timeout_seconds=1, max_bytes=max_bytes)

    if max_bytes == 3:
        with pytest.raises(ContentTooLargeError):
            fetcher.fetch("http://8.8.8.8/")
    else:
        assert fetcher.fetch("http://8.8.8.8/") == ("café", "text/plain")


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


def test_iishko_api_check_does_not_make_a_request_without_key() -> None:
    upstream = Mock(side_effect=AssertionError("request without a key"))
    provider = IishkoProvider(
        api_key=None,
        base_url="https://iishko.test/v1",
        model="test-model",
        timeout_seconds=1,
        transport=httpx.MockTransport(upstream),
    )
    assert provider.api_available(1) is False
    upstream.assert_not_called()


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


def test_qwen_local_uses_paraphrase_prompt_and_local_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "source_language": "ru",
                                    "main_statement": " Первое ",
                                    "context": "Второе.",
                                }
                            )
                        }
                    }
                ]
            },
        )

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
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "in your own words" in body["messages"][0]["content"]
    assert (body["temperature"], body["top_p"], body["top_k"], body["min_p"]) == (0.2, 0.8, 20, 0)
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


def test_annotation_default_upstream_400_keeps_existing_failure_contract() -> None:
    provider = IishkoProvider(
        api_key="secret",
        base_url="https://example.org/v1",
        model="default",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(400, json={"error": {"code": "invalid_request"}})
        ),
    )
    with pytest.raises(AnnotationFailedError):
        provider.annotate(ProviderAnnotationRequest(text="material", params={}))


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        "[]",
        '{"main_statement":"First.","context":"Second."}',
        '{"source_language":"en","main_statement":null,"context":"Second."}',
        '{"source_language":"en","main_statement":" ","context":"Second."}',
    ],
)
def test_qwen_invalid_structured_annotation_is_a_safe_error(content: str) -> None:
    provider = QwenLocalProvider(
        base_url="http://local/v1",
        model="qwen3.5-4b",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        ),
    )
    with pytest.raises(AnnotationFailedError):
        provider.annotate(ProviderAnnotationRequest(text="Source", params={}))


def test_qwen_truncated_structured_annotation_is_rejected() -> None:
    content = json.dumps(
        {"source_language": "en", "main_statement": "First.", "context": "Second."}
    )
    provider = QwenLocalProvider(
        base_url="http://local/v1",
        model="qwen3.5-4b",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"finish_reason": "length", "message": {"content": content}}]},
            )
        ),
    )
    with pytest.raises(AnnotationFailedError):
        provider.annotate(ProviderAnnotationRequest(text="Source", params={}))
