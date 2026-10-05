import http.client
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import urljoin, urlsplit

import dns.exception
import dns.resolver

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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []
        self._skip_depth = 0
        self._main_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag in {"main", "article"}:
            self._main_depth += 1
        if tag in _BLOCK_TAGS:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._append("\n")
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"main", "article"} and self._main_depth:
            self._main_depth -= 1

    def handle_data(self, data: str) -> None:
        self._append(data)

    def _append(self, value: str) -> None:
        if self._skip_depth:
            return
        self.all_parts.append(value)
        if self._main_depth:
            self.main_parts.append(value)


def _normalize(parts: list[str]) -> str:
    lines = (_SPACE.sub(" ", line).strip() for line in "".join(parts).splitlines())
    return "\n".join(line for line in lines if line)


def extract_html_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    main = _normalize(parser.main_parts)
    text = main if main else _normalize(parser.all_parts)
    if not text:
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
        deadline = monotonic() + self._timeout_seconds
        current = url
        for redirect_count in range(self._max_redirects + 1):
            host, port, path, scheme = self._validate_url(current)
            address = self._resolve_public_address(host, port, deadline - monotonic())
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ContentFetchFailedError()
            connection = self._connection(host, port, scheme, address, remaining)
            try:
                connection.request(
                    "GET",
                    path,
                    headers={
                        "Accept": "text/html,text/plain",
                        "Accept-Encoding": "identity",
                        "User-Agent": "babelfish-annotate/1",
                    },
                )
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location or redirect_count == self._max_redirects:
                        raise ContentFetchFailedError()
                    current = urljoin(current, location)
                    continue
                if response.status != 200:
                    raise ContentFetchFailedError()
                content_type = response.headers.get_content_type()
                if content_type not in ("text/html", "text/plain"):
                    raise UnsupportedContentTypeError()
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise UnsupportedContentTypeError()
                data = response.read(self._max_bytes + 1)
                if len(data) > self._max_bytes:
                    raise ContentTooLargeError()
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    return data.decode(charset, errors="replace"), content_type
                except LookupError:
                    return data.decode("utf-8", errors="replace"), content_type
            except (OSError, http.client.HTTPException):
                raise ContentFetchFailedError() from None
            finally:
                connection.close()
        raise ContentFetchFailedError()

    @staticmethod
    def _validate_url(url: str) -> tuple[str, int, str, str]:
        try:
            parsed = urlsplit(url)
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

    def _resolve_public_address(self, host: str, port: int, remaining: float) -> str:
        if remaining <= 0:
            raise ContentFetchFailedError()
        if self._dns_server is None:
            try:
                results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except OSError:
                raise ContentFetchFailedError() from None
            addresses = [item[4][0] for item in results]
        else:
            try:
                ipaddress.ip_address(host)
                addresses = [host]
            except ValueError:
                resolver = dns.resolver.Resolver(configure=False)
                resolver.nameservers = [self._dns_server]
                resolver.lifetime = min(remaining, self._timeout_seconds)
                addresses = []
                for record_type in ("A", "AAAA"):
                    try:
                        answers = resolver.resolve(host, record_type)
                        addresses.extend(str(answer) for answer in answers)
                    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                        continue
                    except dns.exception.DNSException:
                        raise ContentFetchFailedError() from None
        if not addresses:
            raise ContentFetchFailedError()
        if not all(ipaddress.ip_address(address).is_global for address in addresses):
            raise UrlNotAllowedError()
        return addresses[0]

    @staticmethod
    def _connection(
        host: str, port: int, scheme: str, address: str, timeout: float
    ) -> http.client.HTTPConnection:
        if scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                host, port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection._create_connection = lambda _address, timeout=timeout, source_address=None: (
            socket.create_connection(
                (address, port), timeout=timeout, source_address=source_address
            )
        )
        return connection
