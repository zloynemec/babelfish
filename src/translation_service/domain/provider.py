from typing import Protocol

from translation_service.domain.models import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderTranslationRequest,
    ProviderTranslationResult,
)


class TranslatorProvider(Protocol):
    name: str

    def translate(self, request: ProviderTranslationRequest) -> ProviderTranslationResult: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def health(self) -> ProviderHealth: ...
