from collections.abc import Callable
from dataclasses import dataclass, field

from translation_service.domain.models import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderTranslationRequest,
    ProviderTranslationResult,
)


@dataclass(slots=True)
class FakeTranslatorProvider:
    """Configurable provider intended only for tests and local development."""

    name: str = "fake"
    ready: bool = True
    supported_pairs: list[tuple[str, str]] | None = field(default_factory=lambda: [("en", "ru")])
    accepts_params: bool = True
    translate_function: Callable[[ProviderTranslationRequest], str] | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    last_request: ProviderTranslationRequest | None = field(default=None, init=False)

    def translate(self, request: ProviderTranslationRequest) -> ProviderTranslationResult:
        self.last_request = request
        translation = (
            self.translate_function(request)
            if self.translate_function is not None
            else f"translated:{request.text}"
        )
        return ProviderTranslationResult(translation=translation, metadata=self.metadata)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_pairs=self.supported_pairs,
            accepts_params=self.accepts_params,
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(ready=self.ready)
