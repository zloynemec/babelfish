import time

import pytest

from translation_service.core.config import Settings
from translation_service.core.errors import (
    InvalidRequestError,
    TextTooLargeError,
    TranslationFailedError,
    TranslationTimeoutError,
)
from translation_service.domain.models import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderTranslationRequest,
    ProviderTranslationResult,
)
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import TranslatorRegistry
from translation_service.services.translation import TranslationService


def build_service(
    provider: FakeTranslatorProvider,
    *,
    default_translator: str = "fake",
    max_text_length: int = 20_000,
    timeout: float = 1,
) -> TranslationService:
    registry = TranslatorRegistry()
    registry.register(provider)
    settings = Settings(
        default_translator=default_translator,
        max_text_length=max_text_length,
        translation_timeout_seconds=timeout,
    )
    return TranslationService(registry, settings)


@pytest.mark.anyio
async def test_defaults_and_params_are_forwarded_unchanged() -> None:
    provider = FakeTranslatorProvider(name="fake")
    service = build_service(provider)
    params = {"mode": "test", "nested": {"value": 1}}

    result = await service.translate(
        text="Hello",
        target_language="ru",
        translator_params=params,
    )

    assert result.source_language == "en"
    assert result.translator == "fake"
    assert provider.last_request is not None
    assert provider.last_request.params is params


@pytest.mark.anyio
async def test_explicit_source_and_translator_are_used() -> None:
    default_provider = FakeTranslatorProvider(name="fake")
    selected_provider = FakeTranslatorProvider(name="other", supported_pairs=[("de", "fr")])
    registry = TranslatorRegistry()
    registry.register(default_provider)
    registry.register(selected_provider)
    service = TranslationService(registry, Settings(default_translator="fake"))

    result = await service.translate(
        text="Hallo",
        source_language="de",
        target_language="fr",
        translator="OTHER",
    )

    assert result.source_language == "de"
    assert result.translator == "other"
    assert default_provider.last_request is None
    assert selected_provider.last_request is not None


@pytest.mark.anyio
async def test_whitespace_only_text_is_rejected() -> None:
    service = build_service(FakeTranslatorProvider())

    with pytest.raises(InvalidRequestError):
        await service.translate(text=" \n ", target_language="ru")


@pytest.mark.anyio
async def test_text_over_configured_limit_is_rejected() -> None:
    service = build_service(FakeTranslatorProvider(), max_text_length=5)

    with pytest.raises(TextTooLargeError) as error:
        await service.translate(text="123456", target_language="ru")

    assert error.value.details == {"max_text_length": 5, "actual_length": 6}


@pytest.mark.anyio
async def test_unexpected_provider_error_is_normalized() -> None:
    provider = FakeTranslatorProvider(
        translate_function=lambda request: (_ for _ in ()).throw(RuntimeError("secret /tmp/path"))
    )
    service = build_service(provider)

    with pytest.raises(TranslationFailedError) as error:
        await service.translate(text="Hello", target_language="ru")

    assert "secret" not in error.value.message
    assert "/tmp/path" not in error.value.details.values()


@pytest.mark.anyio
async def test_timeout_is_normalized() -> None:
    def slow_translate(request: ProviderTranslationRequest) -> str:
        del request
        time.sleep(0.1)
        return "late"

    service = build_service(FakeTranslatorProvider(translate_function=slow_translate), timeout=0.01)

    with pytest.raises(TranslationTimeoutError):
        await service.translate(text="Hello", target_language="ru")


class ExplodingHealthProvider:
    name = "broken"

    def health(self) -> ProviderHealth:
        raise RuntimeError("provider internals")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_pairs=None, accepts_params=False)

    def translate(self, request: ProviderTranslationRequest) -> ProviderTranslationResult:
        raise AssertionError(request)


@pytest.mark.anyio
async def test_health_error_is_normalized() -> None:
    registry = TranslatorRegistry()
    registry.register(ExplodingHealthProvider())
    service = TranslationService(registry, Settings(default_translator="broken"))

    with pytest.raises(TranslationFailedError):
        await service.translate(text="Hello", target_language="ru")
