import re
from collections.abc import Mapping
from copy import copy
from difflib import SequenceMatcher
from functools import lru_cache
from time import perf_counter
from typing import Any

import anyio
from py3langid.langid import MODEL_FILE, LanguageIdentifier

from translation_service.core.config import Settings
from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotationTimeoutError,
    AnnotatorUnavailableError,
    ApplicationError,
    ContentTooLargeError,
    IncompleteAnnotationError,
)
from translation_service.core.workers import WorkerPool
from translation_service.domain.annotation import ProviderAnnotationRequest
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.content import SafePageFetcher, read_page_text
from translation_service.services.generation_validation import has_invented_mixed_word

_SENTENCE_END = re.compile(
    r"""[.!?\u2026]+["')\]\u201d\u2019\u00bb]*(?:\s|$)|[\u3002\uff01\uff1f\u061f]+"""
)
# shortcut: This list covers common abbreviations. Extend it for observed false boundaries.
_ABBREVIATION = re.compile(
    r"\b(?:тыс|млн|млрд|руб|ул|д|к|г|mr|mrs|ms|dr|prof)\.(?=\s)",  # noqa: RUF001
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _language_identifier() -> LanguageIdentifier:
    return LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)


def _detect_language(text: str) -> str | None:
    # shortcut: Skip low-confidence guesses on short or ambiguous text.
    if sum(char.isalpha() for char in text) < 24:
        return None
    language, confidence = _language_identifier().classify(text)
    return str(language) if confidence >= 0.85 else None


class AnnotationService:
    def __init__(
        self,
        registry: AnnotatorRegistry,
        settings: Settings,
        fetcher: SafePageFetcher | None = None,
        *,
        workers: WorkerPool | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._workers = workers or WorkerPool(settings.max_concurrent_operations)
        self._fetcher = fetcher or SafePageFetcher(
            timeout_seconds=settings.annotation_fetch_timeout_seconds,
            max_bytes=settings.annotation_max_download_bytes,
            dns_server=settings.annotation_dns_server,
        )

    def with_workers(self, workers: WorkerPool) -> "AnnotationService":
        service = copy(self)
        service._workers = workers
        return service

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

        def invoke() -> tuple[str, bool]:
            prepared, truncated = self._prepare(url=url, html=html, text=text)
            anyio.from_thread.check_cancelled()
            if not provider.health().ready:
                raise AnnotatorUnavailableError(details={"annotator": provider_name})
            violation = None
            source_language = _detect_language(prepared)
            source_words = (
                re.findall(r"\w+", prepared.casefold()) if provider_name == "qwen_local" else []
            )
            for _ in range(2):
                anyio.from_thread.check_cancelled()
                try:
                    result = provider.annotate(
                        ProviderAnnotationRequest(
                            text=prepared,
                            params=annotator_params or {},
                            format_violation=violation,
                            source_language=source_language,
                        )
                    )
                except IncompleteAnnotationError:
                    violation = "it exceeded the output limit"
                    continue
                anyio.from_thread.check_cancelled()
                annotation = result.annotation.strip()
                if provider_name == "qwen_local":
                    violation = _qwen_violation(annotation, prepared, source_words)
                    if violation:
                        continue
                countable = _ABBREVIATION.sub("", annotation)
                endings = list(_SENTENCE_END.finditer(countable))
                if len(endings) not in (2, 3) or endings[-1].end() != len(countable):
                    violation = "return two or three complete sentences with no unfinished ending"
                    continue
                output_language = _detect_language(annotation) if source_language else None
                if output_language and output_language != source_language:
                    violation = "the answer changed the language of the source"
                    continue
                return annotation, truncated

            raise AnnotationFailedError(details={"annotator": provider_name})

        try:
            with anyio.fail_after(self._settings.annotation_timeout_seconds):
                annotation, truncated = await self._workers.run(invoke)
            return {
                "annotation": annotation,
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
        prepared = read_page_text(
            self._fetcher,
            url=url,
            html=html,
            max_html_chars=self._settings.annotation_max_input_chars,
        )
        max_chars = self._settings.annotation_max_text_chars
        return prepared[:max_chars], len(prepared) > max_chars


def _qwen_violation(annotation: str, prepared: str, source_words: list[str]) -> str | None:
    if has_invented_mixed_word(annotation, prepared):
        return "output mixes Latin and Cyrillic within a new word; rewrite it"
    if len(source_words) < 30:
        return None
    result_words = re.findall(r"\w+", annotation.casefold())
    if len(result_words) > 25:
        return "summary is too long; use at most 25 words total in two sentences"
    if SequenceMatcher(None, source_words, result_words, autojunk=False).ratio() >= 0.85:
        return "output copies the source; write a shorter summary in new words"
    return None
