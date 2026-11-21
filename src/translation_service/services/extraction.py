import json
from collections.abc import Iterator, Mapping
from time import perf_counter
from typing import Any

import anyio

from translation_service.core.config import Settings
from translation_service.core.errors import (
    AnnotatorUnavailableError,
    ApplicationError,
    ContentExtractionFailedError,
    ContentExtractionTimeoutError,
    ContentNotExtractableError,
    ContentTooLargeError,
)
from translation_service.core.workers import WorkerPool
from translation_service.domain.content import ContentProvider, ProviderContentRequest
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.content import SafePageFetcher, read_page_text

_CONTENT_BATCH_CHARS = 8_000


class ContentService:
    def __init__(
        self,
        registry: AnnotatorRegistry,
        settings: Settings,
        *,
        workers: WorkerPool,
        fetcher: SafePageFetcher | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._workers = workers
        self._fetcher = fetcher or SafePageFetcher(
            timeout_seconds=settings.annotation_fetch_timeout_seconds,
            max_bytes=settings.annotation_max_download_bytes,
            dns_server=settings.annotation_dns_server,
        )

    async def extract_content(
        self,
        *,
        url: str | None,
        html: str | None,
        text: str | None,
        annotator: str | None,
        annotator_params: Mapping[str, Any],
    ) -> dict[str, Any]:
        provider = self._registry.get(annotator or self._settings.default_annotator)
        provider_name = self._registry.normalize_name(provider.name)
        if not isinstance(provider, ContentProvider):
            raise AnnotatorUnavailableError(details={"annotator": provider_name})
        started = perf_counter()

        def invoke() -> str:
            if text is not None:
                if len(text) > self._settings.content_max_input_chars:
                    raise ContentTooLargeError()
                prepared = text
            else:
                prepared = read_page_text(
                    self._fetcher,
                    url=url,
                    html=html,
                    max_html_chars=self._settings.content_max_input_chars,
                    preserve_content_blocks=True,
                )
            blocks = [line for line in prepared.splitlines() if line.strip()]
            anyio.from_thread.check_cancelled()
            if not provider.health().ready:
                raise AnnotatorUnavailableError(details={"annotator": provider_name})

            keep: set[int] = set()
            for batch in _content_batches(blocks):
                anyio.from_thread.check_cancelled()
                numbered = "\n".join(f"{index}: {part}" for index, (_, part) in enumerate(batch, 1))
                selection = json.loads(
                    provider.extract_content(ProviderContentRequest(numbered, annotator_params))
                )
                if not isinstance(selection, dict) or set(selection) != {"discard"}:
                    raise ValueError("invalid content selection")
                discard = selection["discard"]
                if not isinstance(discard, list) or any(
                    type(index) is not int or not 1 <= index <= len(batch) for index in discard
                ):
                    raise ValueError("invalid content block numbers")
                discarded = set(discard)
                # A long source line is removed only when every part is boilerplate.
                keep.update(
                    block_index
                    for index, (block_index, _) in enumerate(batch, 1)
                    if index not in discarded
                )
            if not keep:
                raise ContentNotExtractableError()
            return "\n".join(blocks[index] for index in sorted(keep))

        try:
            with anyio.fail_after(self._settings.content_timeout_seconds):
                content = await self._workers.run(invoke)
        except TimeoutError:
            raise ContentExtractionTimeoutError(details={"annotator": provider_name}) from None
        except ApplicationError:
            raise
        except Exception:
            raise ContentExtractionFailedError(details={"annotator": provider_name}) from None
        return {
            "content": content,
            "annotator": provider_name,
            "metadata": {
                "duration_ms": max(0, int((perf_counter() - started) * 1000)),
                "truncated": False,
            },
        }


def _content_batches(blocks: list[str]) -> Iterator[list[tuple[int, str]]]:
    prefix_budget = 10
    max_part_chars = _CONTENT_BATCH_CHARS - prefix_budget
    batch: list[tuple[int, str]] = []
    size = 0
    for index, block in enumerate(blocks):
        for start in range(0, len(block), max_part_chars):
            part = block[start : start + max_part_chars]
            cost = len(part) + prefix_budget
            if size + cost > _CONTENT_BATCH_CHARS:
                yield batch
                batch = []
                size = 0
            batch.append((index, part))
            size += cost
    if batch:
        yield batch
