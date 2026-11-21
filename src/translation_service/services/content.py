import ipaddress
import re
import ssl
from dataclasses import dataclass
from email.message import Message
from html.parser import HTMLParser
from unicodedata import category
from urllib.parse import SplitResult, urljoin, urlsplit

import anyio
import dns.asyncresolver
import dns.exception
import httpx

from translation_service.core.errors import (
    ContentFetchFailedError,
    ContentNotExtractableError,
    ContentTooLargeError,
    UnsupportedContentTypeError,
    UrlNotAllowedError,
)

_SKIP_TAGS = frozenset(
    {
        "head",
        "script",
        "style",
        "noscript",
        "template",
        "nav",
        "header",
        "footer",
        "aside",
        "svg",
        "iframe",
        "form",
        "button",
        "select",
    }
)
_BLOCK_TAGS = frozenset(
    {"article", "main", "section", "div", "p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SPACE = re.compile(r"\s+")
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@dataclass
class _Section:
    all_start: int
    main_start: int
    outside_article: bool
    has_contact_form: bool = False


class _TextExtractor(HTMLParser):
    def __init__(self, *, preserve_content_blocks: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_tags = _SKIP_TAGS
        self._block_tags = _BLOCK_TAGS
        self._table_cells: frozenset[str] = frozenset()
        if preserve_content_blocks:
            self._skip_tags = _SKIP_TAGS - {"header"}
            self._block_tags = _BLOCK_TAGS | {
                "header",
                "blockquote",
                "figcaption",
                "dt",
                "dd",
                "tr",
            }
            self._table_cells = frozenset({"td", "th"})
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []
        self._skip_depth = 0
        self._main_depth = 0
        self._preserve_content_blocks = preserve_content_blocks
        self._inline_boundary = False
        self._path: list[str] = []
        self._sections: list[_Section] = []
        self._contact_form_section: _Section | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._inline_boundary = True
        if self._preserve_content_blocks:
            if tag == "section":
                self._sections.append(
                    _Section(len(self.all_parts), len(self.main_parts), "article" not in self._path)
                )
            elif tag == "article":
                for section in self._sections:
                    section.outside_article = False
            elif tag == "form" and self._path[-1:] == ["section"] and self._sections:
                if (dict(attrs).get("method") or "").lower() == "post":
                    self._contact_form_section = self._sections[-1]
            elif (
                tag == "input"
                and self._contact_form_section is not None
                and (dict(attrs).get("type") or "").lower() in {"email", "tel"}
            ):
                self._contact_form_section.has_contact_form = True
            if tag not in _VOID_TAGS:
                self._path.append(tag)
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag in {"main", "article"}:
            self._main_depth += 1
        if tag in self._block_tags:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        self._inline_boundary = True
        if tag in self._block_tags:
            self._append("\n")
        if tag in self._table_cells:
            self._append(" ")
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"main", "article"} and self._main_depth:
            self._main_depth -= 1
        if self._preserve_content_blocks:
            if tag == "form":
                self._contact_form_section = None
            elif tag == "section" and self._sections:
                section = self._sections.pop()
                if section.outside_article and section.has_contact_form:
                    del self.all_parts[section.all_start :]
                    del self.main_parts[section.main_start :]
            if self._path and self._path[-1] == tag:
                self._path.pop()
            elif tag in self._path:
                closing = len(self._path) - 1 - self._path[::-1].index(tag)
                del self._path[closing:]

    def handle_data(self, data: str) -> None:
        # Inline element boundaries can be the only separation between a price and nearby copy.
        if (
            self._inline_boundary
            and data
            and data[0].isalpha()
            and self.all_parts
            and category(self.all_parts[-1][-1]) == "Sc"
        ):
            self._append("\n" if data[0].isupper() and data[1:2].islower() else " ")
        self._inline_boundary = False
        self._append(data)

    def _append(self, value: str) -> None:
        if not value or self._skip_depth:
            return
        self.all_parts.append(value)
        if self._main_depth:
            self.main_parts.append(value)


def _normalize(parts: list[str]) -> str:
    lines = (_SPACE.sub(" ", line).strip() for line in "".join(parts).splitlines())
    return "\n".join(line for line in lines if line)


def extract_html_text(html: str, *, preserve_content_blocks: bool = False) -> str:
    parser = _TextExtractor(preserve_content_blocks=preserve_content_blocks)
    parser.feed(html)
    parser.close()
    main = _normalize(parser.main_parts)
    text = main if main else _normalize(parser.all_parts)
    if not text:
        raise ContentNotExtractableError()
    return text


def parse_page_url(url: str) -> SplitResult:
    parsed = urlsplit(url)
    if not parsed.scheme or re.search(r"[\s\x00-\x1f\x7f]", url):
        raise ValueError("invalid URL")
    if parsed.scheme in ("http", "https"):
        if not parsed.hostname:
            raise ValueError("invalid URL")
        _ = parsed.port  # urllib.parse validates the port on access.
    return parsed


def read_page_text(
    fetcher: "SafePageFetcher",
    *,
    url: str | None,
    html: str | None,
    max_html_chars: int,
    preserve_content_blocks: bool = False,
) -> str:
    if html is not None:
        if len(html) > max_html_chars:
            raise ContentTooLargeError()
        page, content_type = html, "text/html"
    else:
        assert url is not None
        page, content_type = fetcher.fetch(url)
    text = (
        extract_html_text(page, preserve_content_blocks=preserve_content_blocks)
        if content_type == "text/html"
        else page
    )
    if not text.strip():
        raise ContentNotExtractableError()
    return text


class SafePageFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int = 3,
        dns_server: str | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._dns_server = dns_server

    def fetch(self, url: str) -> tuple[str, str]:
        return anyio.run(self._fetch, url)

    async def _fetch(self, url: str) -> tuple[str, str]:
        try:
            with anyio.fail_after(self._timeout_seconds):
                async with httpx.AsyncHTTPTransport(
                    verify=ssl.create_default_context(),
                    trust_env=False,
                    # Different redirect hosts can share an IP but require separate TLS sessions.
                    limits=httpx.Limits(max_keepalive_connections=0),
                ) as transport:
                    return await self._download(url, transport)
        except (OSError, ValueError, dns.exception.DNSException, httpx.HTTPError, httpx.InvalidURL):
            raise ContentFetchFailedError() from None

    async def _download(self, url: str, transport: httpx.AsyncBaseTransport) -> tuple[str, str]:
        for redirect_count in range(self._max_redirects + 1):
            host, port, path, scheme = self._validate_url(url)
            address = await self._resolve_public_address(host)
            host = host.encode("idna").decode("ascii")
            authority = f"[{host}]" if ":" in host else host
            if port != (443 if scheme == "https" else 80):
                authority = f"{authority}:{port}"
            request = httpx.Request(
                "GET",
                httpx.URL(scheme=scheme, host=address, port=port),
                headers={
                    "Host": authority,
                    "Accept": "text/html,text/plain",
                    "Accept-Encoding": "identity",
                    "User-Agent": "babelfish-annotate/1",
                },
                extensions={"sni_hostname": host, "target": path.encode("ascii")},
            )
            response = await transport.handle_async_request(request)
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location or redirect_count == self._max_redirects:
                        raise ContentFetchFailedError()
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    raise ContentFetchFailedError()
                return await self._read_page(response)
            finally:
                with anyio.CancelScope(shield=True):
                    await response.aclose()
        raise ContentFetchFailedError()

    async def _read_page(self, response: httpx.Response) -> tuple[str, str]:
        headers = Message()
        if value := response.headers.get("Content-Type"):
            headers["Content-Type"] = value
        content_type = headers.get_content_type()
        if (
            content_type not in ("text/html", "text/plain")
            or response.headers.get("Content-Encoding", "identity").lower() != "identity"
        ):
            raise UnsupportedContentTypeError()
        data = bytearray()
        async for chunk in response.aiter_raw():
            if len(data) + len(chunk) > self._max_bytes:
                raise ContentTooLargeError()
            data.extend(chunk)
        charset = headers.get_content_charset() or "utf-8"
        try:
            return data.decode(charset, errors="replace"), content_type
        except LookupError:
            return data.decode("utf-8", errors="replace"), content_type

    @staticmethod
    def _validate_url(url: str) -> tuple[str, int, str, str]:
        try:
            parsed = parse_page_url(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("invalid URL")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("credentials not allowed")
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            return parsed.hostname, port, path, parsed.scheme
        except ValueError:
            raise UrlNotAllowedError() from None

    async def _resolve_public_address(self, host: str) -> str:
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            resolver = dns.asyncresolver.Resolver(configure=self._dns_server is None)
            if self._dns_server is not None:
                resolver.nameservers = [self._dns_server]
            remaining = anyio.current_effective_deadline() - anyio.current_time()
            answers = await resolver.resolve_name(host, lifetime=remaining)
            addresses = [ipaddress.ip_address(address) for address in answers.addresses()]
        if not addresses:
            raise ContentFetchFailedError()
        if not all(address.is_global for address in addresses):
            raise UrlNotAllowedError()
        return str(min(addresses, key=lambda address: address.version))
