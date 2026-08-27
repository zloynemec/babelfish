from collections.abc import Mapping
from time import perf_counter
from typing import Any

import anyio

from translation_service.core.config import Settings
from translation_service.core.errors import (
    ApplicationError,
    InvalidRequestError,
    InvalidTranslatorParamsError,
    TextTooLargeError,
    TranslationFailedError,
    TranslationTimeoutError,
    TranslatorUnavailableError,
    UnsupportedLanguagePairError,
)
from translation_service.domain.models import ProviderTranslationRequest, TranslationResult
from translation_service.services.registry import TranslatorRegistry


class TranslationService:
    def __init__(self, registry: TranslatorRegistry, settings: Settings) -> None:
        self._registry = registry
        self._settings = settings

    async def translate(
        self,
        *,
        text: str,
        target_language: str,
        source_language: str | None = None,
        translator: str | None = None,
        translator_params: Mapping[str, Any] | None = None,
    ) -> TranslationResult:
        source = source_language or self._settings.default_source_language
        provider_name = translator or self._settings.default_translator
        params = {} if translator_params is None else translator_params

        if not text.strip():
            raise InvalidRequestError(
                "Text must not be empty or whitespace-only",
                details={"field": "text"},
            )
        if len(text) > self._settings.max_text_length:
            raise TextTooLargeError(
                details={
                    "max_text_length": self._settings.max_text_length,
                    "actual_length": len(text),
                }
            )

        provider = self._registry.get(provider_name)
        normalized_provider_name = self._registry.normalize_name(provider.name)

        try:
            health = provider.health()
            if not health.ready:
                raise TranslatorUnavailableError(details={"translator": normalized_provider_name})

            capabilities = provider.capabilities()
            if params and not capabilities.accepts_params:
                raise InvalidTranslatorParamsError(
                    details={
                        "translator": normalized_provider_name,
                        "unknown_parameters": sorted(params),
                    }
                )
            if (
                capabilities.supported_pairs is not None
                and (source, target_language) not in capabilities.supported_pairs
            ):
                raise UnsupportedLanguagePairError(
                    details={
                        "translator": normalized_provider_name,
                        "source_language": source,
                        "target_language": target_language,
                    }
                )

            provider_request = ProviderTranslationRequest(
                text=text,
                source_language=source,
                target_language=target_language,
                params=params,
            )
            started_at = perf_counter()
            with anyio.fail_after(self._settings.translation_timeout_seconds):
                provider_result = await anyio.to_thread.run_sync(
                    provider.translate,
                    provider_request,
                    abandon_on_cancel=True,
                )
            duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        except TimeoutError:
            raise TranslationTimeoutError(
                details={"translator": normalized_provider_name}
            ) from None
        except ApplicationError:
            raise
        except Exception:
            raise TranslationFailedError(details={"translator": normalized_provider_name}) from None

        metadata = dict(provider_result.metadata)
        metadata["duration_ms"] = duration_ms
        return TranslationResult(
            translation=provider_result.translation,
            source_language=source,
            target_language=target_language,
            translator=normalized_provider_name,
            metadata=metadata,
        )
