from dataclasses import dataclass, field

import pytest

from translation_service.core.errors import (
    InvalidTranslatorParamsError,
    TranslationFailedError,
    TranslatorUnavailableError,
    UnsupportedLanguagePairError,
)
from translation_service.domain.models import ProviderTranslationRequest
from translation_service.providers.argos import (
    ArgosLanguage,
    ArgosProvider,
    _configure_argos_runtime,
)


@dataclass
class StubLanguage:
    code: str
    translations_from: list["StubTranslation"] = field(default_factory=list)


@dataclass
class StubTranslation:
    to_lang: StubLanguage
    result: str = "Привет"
    error: Exception | None = None

    def translate(self, text: str) -> str:
        if self.error is not None:
            raise self.error
        assert text == "Hello"
        return self.result


def request(**overrides: object) -> ProviderTranslationRequest:
    values = {
        "text": "Hello",
        "source_language": "en",
        "target_language": "ru",
        "params": {},
    }
    values.update(overrides)
    return ProviderTranslationRequest(**values)  # type: ignore[arg-type]


def language_pair() -> tuple[StubLanguage, StubLanguage]:
    source = StubLanguage("en")
    target = StubLanguage("ru")
    source.translations_from.append(StubTranslation(to_lang=target))
    return source, target


def test_health_and_capabilities_reflect_installed_models() -> None:
    source, target = language_pair()
    provider = ArgosProvider(language_loader=lambda: [source, target])

    assert provider.health().ready is True
    assert provider.health().detail is None
    assert provider.capabilities().supported_pairs == [("en", "ru")]
    assert provider.capabilities().accepts_params is False


def test_no_installed_model_is_unavailable() -> None:
    provider = ArgosProvider(language_loader=lambda: [])

    assert provider.health().ready is False
    assert provider.capabilities().supported_pairs == []
    with pytest.raises(TranslatorUnavailableError):
        provider.translate(request())


def test_supported_pair_is_translated() -> None:
    source, target = language_pair()
    provider = ArgosProvider(language_loader=lambda: [source, target])

    result = provider.translate(request())

    assert result.translation == "Привет"
    assert result.metadata == {}


def test_unknown_params_are_rejected() -> None:
    source, target = language_pair()
    provider = ArgosProvider(language_loader=lambda: [source, target])

    with pytest.raises(InvalidTranslatorParamsError):
        provider.translate(request(params={"beam_size": 5}))


def test_unsupported_pair_is_normalized() -> None:
    source, target = language_pair()
    provider = ArgosProvider(language_loader=lambda: [source, target])

    with pytest.raises(UnsupportedLanguagePairError) as error:
        provider.translate(request(target_language="de"))

    assert error.value.details["source_language"] == "en"
    assert error.value.details["target_language"] == "de"


def test_argos_exception_is_normalized_without_leaking_details() -> None:
    source, target = language_pair()
    source.translations_from[0].error = RuntimeError("secret /private/model/path")
    provider = ArgosProvider(language_loader=lambda: [source, target])

    with pytest.raises(TranslationFailedError) as error:
        provider.translate(request())

    assert "secret" not in error.value.message
    assert "/private/model/path" not in error.value.details.values()


def test_loader_failure_reports_unavailable_health() -> None:
    def fail_to_load() -> list[ArgosLanguage]:
        raise RuntimeError("broken installation")

    provider = ArgosProvider(language_loader=fail_to_load)

    assert provider.health().ready is False
    assert provider.capabilities().supported_pairs == []
    with pytest.raises(TranslatorUnavailableError):
        provider.translate(request())


def test_argos_uses_minisbd_sentence_splitter() -> None:
    from argostranslate import settings

    _configure_argos_runtime()

    assert settings.chunk_type is settings.ChunkType.MINISBD
