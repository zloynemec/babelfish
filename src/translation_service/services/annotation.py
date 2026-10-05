import re
from collections.abc import Mapping
from time import perf_counter
from typing import Any

import anyio

from translation_service.core.config import Settings
from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotationTimeoutError,
    AnnotatorUnavailableError,
    ApplicationError,
    ContentNotExtractableError,
    ContentTooLargeError,
)
from translation_service.domain.annotation import ProviderAnnotationRequest
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.content import SafePageFetcher, extract_html_text

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
_ABBREVIATION = re.compile(r"\b(?:тыс|млн|млрд|руб|ул|д|к|г)\.(?=\s)", re.IGNORECASE)  # noqa: RUF001


class AnnotationService:
    def __init__(
        self,
        registry: AnnotatorRegistry,
        settings: Settings,
        fetcher: SafePageFetcher | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._fetcher = fetcher or SafePageFetcher(
            timeout_seconds=settings.annotation_fetch_timeout_seconds,
            max_bytes=settings.annotation_max_download_bytes,
            dns_server=settings.annotation_dns_server,
        )

    async def annotate(
        self,
        *,
        url: str | None = None,
        html: str | None = None,
        text: str | None = None,
        annotator: str | None = None,
        annotator_params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider = self._registry.get(annotator or self._settings.default_annotator)
        provider_name = self._registry.normalize_name(provider.name)
        started = perf_counter()
        try:
            with anyio.fail_after(self._settings.annotation_timeout_seconds):
                prepared, truncated = await anyio.to_thread.run_sync(
                    lambda: self._prepare(url=url, html=html, text=text),
                    abandon_on_cancel=True,
                )
                if not provider.health().ready:
                    raise AnnotatorUnavailableError(details={"annotator": provider_name})
                result = await anyio.to_thread.run_sync(
                    provider.annotate,
                    ProviderAnnotationRequest(text=prepared, params=annotator_params or {}),
                    abandon_on_cancel=True,
                )
            annotation = result.annotation.strip()
            countable = _ABBREVIATION.sub("", annotation)
            if len(_SENTENCE_END.findall(countable)) not in (2, 3):
                raise AnnotationFailedError(details={"annotator": provider_name})
            return {
                "annotation": annotation,
                "language": "ru",
                "annotator": provider_name,
                "metadata": {
                    "duration_ms": max(0, int((perf_counter() - started) * 1000)),
                    "truncated": truncated,
                },
            }
        except TimeoutError:
            raise AnnotationTimeoutError(details={"annotator": provider_name}) from None
        except ApplicationError:
            raise
        except Exception:
            raise AnnotationFailedError(details={"annotator": provider_name}) from None

    def _prepare(self, *, url: str | None, html: str | None, text: str | None) -> tuple[str, bool]:
        if text is not None:
            if len(text) > self._settings.annotation_max_text_chars:
                raise ContentTooLargeError()
            return text, False
        if html is not None:
            if len(html) > self._settings.annotation_max_input_chars:
                raise ContentTooLargeError()
            prepared = extract_html_text(html)
        else:
            assert url is not None
            fetched, content_type = self._fetcher.fetch(url)
            prepared = extract_html_text(fetched) if content_type == "text/html" else fetched
        if not prepared.strip():
            raise ContentNotExtractableError()
        max_chars = self._settings.annotation_max_text_chars
        return prepared[:max_chars], len(prepared) > max_chars
