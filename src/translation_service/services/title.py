import re
from collections.abc import Mapping
from time import perf_counter
from typing import Any

import anyio

from translation_service.core.config import Settings
from translation_service.core.errors import (
    AnnotationTimeoutError,
    AnnotatorUnavailableError,
    ApplicationError,
    InsufficientContentError,
    InvalidTitleError,
    TextTooLargeError,
    TitleFailedError,
    UnsupportedTitleLanguageError,
)
from translation_service.core.workers import WorkerPool
from translation_service.domain.title import (
    INSUFFICIENT_CONTENT,
    ProviderTitleRequest,
    TitleProvider,
)
from translation_service.services.annotator_registry import AnnotatorRegistry


class TitleService:
    def __init__(
        self, registry: AnnotatorRegistry, settings: Settings, *, workers: WorkerPool
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._workers = workers

    async def generate(
        self,
        *,
        text: str,
        target_language: str,
        annotator: str | None,
        annotator_params: Mapping[str, Any],
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        if len(text) > 30_000:
            raise TextTooLargeError(details={"max_text_length": 30_000})
        if target_language not in ("ru", "en"):
            raise UnsupportedTitleLanguageError()
        provider = self._registry.get(annotator or self._settings.default_annotator)
        if not isinstance(provider, TitleProvider):
            raise AnnotatorUnavailableError()
        started = perf_counter()

        def invoke() -> str:
            if not provider.health().ready:
                raise AnnotatorUnavailableError()
            violation = None
            for attempt in range(1, 3):
                anyio.from_thread.check_cancelled()
                operation["attempts"] = attempt
                try:
                    result = provider.title(
                        ProviderTitleRequest(
                            text=text,
                            target_language=target_language,
                            params=annotator_params,
                            format_violation=violation,
                        )
                    )
                    anyio.from_thread.check_cancelled()
                    title, violation = validate_title(result.title)
                except InvalidTitleError:
                    title, violation = "", "provider response must contain a plain text title"
                if violation is None:
                    return title
            raise InvalidTitleError()

        try:
            with anyio.fail_after(self._settings.annotation_timeout_seconds):
                title = await self._workers.run(invoke)
            operation["title_length"] = len(title)
            return {
                "title": title,
                "target_language": target_language,
                "metadata": {"duration_ms": max(0, int((perf_counter() - started) * 1000))},
            }
        except TimeoutError:
            raise AnnotationTimeoutError() from None
        except ApplicationError:
            raise
        except Exception:
            raise TitleFailedError() from None


def validate_title(value: str) -> tuple[str, str | None]:
    if not isinstance(value, str):
        return "", "output must be a string"
    if any(char in value for char in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
        return "", "output must be a single line"
    title = " ".join(value.split())
    for left, right in (('"', '"'), ("'", "'"), ("«", "»"), ("“", "”")):
        if title.startswith(left) and title.endswith(right):
            title = title[1:-1].strip()
            break
    if title == INSUFFICIENT_CONTENT:
        raise InsufficientContentError()
    if not title:
        return "", "output must not be empty"
    if len(title) > 120:
        return "", "output exceeds 120 Unicode characters"
    if re.search(
        r"[<>`]|\*\*|__|(?<!\w)[*_].+[*_](?!\w)|^#{1,6} |^[-+] |^\d+[.)] |!?\[.*\]\(", title
    ):
        return "", "output must be plain text without Markdown or HTML"
    if any(not char.isprintable() for char in title):
        return "", "output contains control characters"
    return title, None
