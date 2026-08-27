from collections.abc import Callable, Sequence
from threading import Lock
from typing import Protocol, cast

from translation_service.core.errors import (
    ApplicationError,
    InvalidTranslatorParamsError,
    TranslationFailedError,
    TranslatorUnavailableError,
    UnsupportedLanguagePairError,
)
from translation_service.domain.models import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderTranslationRequest,
    ProviderTranslationResult,
)


class ArgosTranslation(Protocol):
    to_lang: "ArgosLanguage"

    def translate(self, text: str) -> str: ...


class ArgosLanguage(Protocol):
    code: str
    translations_from: list[ArgosTranslation]


LanguageLoader = Callable[[], Sequence[ArgosLanguage]]
_CONFIGURATION_LOCK = Lock()
_RUNTIME_CONFIGURED = False


def _configure_argos_runtime() -> None:
    """Use Argos' lightweight sentence splitter, allowing its normal model fetch."""
    global _RUNTIME_CONFIGURED

    with _CONFIGURATION_LOCK:
        if _RUNTIME_CONFIGURED:
            return

        from argostranslate import settings
        from argostranslate import translate as argos_translate

        settings.chunk_type = settings.ChunkType.MINISBD
        argos_translate.get_installed_languages.cache_clear()
        argos_translate.installed_translates.clear()
        _RUNTIME_CONFIGURED = True


def _load_installed_languages() -> Sequence[ArgosLanguage]:
    _configure_argos_runtime()
    from argostranslate.translate import get_installed_languages

    return cast(Sequence[ArgosLanguage], get_installed_languages())


class ArgosProvider:
    """Adapter for locally installed Argos Translate models."""

    name = "argos"

    def __init__(self, language_loader: LanguageLoader | None = None) -> None:
        self._language_loader = language_loader or _load_installed_languages

    def translate(self, request: ProviderTranslationRequest) -> ProviderTranslationResult:
        if request.params:
            raise InvalidTranslatorParamsError(
                details={
                    "translator": self.name,
                    "unknown_parameters": sorted(request.params),
                }
            )

        try:
            languages = list(self._language_loader())
        except Exception:
            raise TranslatorUnavailableError(details={"translator": self.name}) from None

        translation = self._find_translation(
            languages,
            request.source_language,
            request.target_language,
        )
        if translation is None:
            details = {
                "translator": self.name,
                "source_language": request.source_language,
                "target_language": request.target_language,
            }
            if not self._supported_pairs(languages, include_identity=False):
                raise TranslatorUnavailableError(details={"translator": self.name})
            raise UnsupportedLanguagePairError(details=details)

        try:
            translated_text = translation.translate(request.text)
        except ApplicationError:
            raise
        except Exception:
            raise TranslationFailedError(details={"translator": self.name}) from None

        return ProviderTranslationResult(translation=translated_text, metadata={})

    def capabilities(self) -> ProviderCapabilities:
        try:
            languages = list(self._language_loader())
        except Exception:
            return ProviderCapabilities(supported_pairs=[], accepts_params=False)

        return ProviderCapabilities(
            supported_pairs=self._supported_pairs(languages),
            accepts_params=False,
        )

    def health(self) -> ProviderHealth:
        try:
            languages = list(self._language_loader())
            model_pairs = self._supported_pairs(languages, include_identity=False)
        except Exception:
            return ProviderHealth(ready=False, detail="Argos Translate is unavailable")

        if not model_pairs:
            return ProviderHealth(
                ready=False,
                detail="No Argos translation models are installed",
            )
        return ProviderHealth(ready=True)

    @staticmethod
    def _find_translation(
        languages: Sequence[ArgosLanguage],
        source_language: str,
        target_language: str,
    ) -> ArgosTranslation | None:
        source = next(
            (language for language in languages if language.code == source_language),
            None,
        )
        if source is None:
            return None
        return next(
            (
                translation
                for translation in source.translations_from
                if translation.to_lang.code == target_language
            ),
            None,
        )

    @staticmethod
    def _supported_pairs(
        languages: Sequence[ArgosLanguage],
        *,
        include_identity: bool = True,
    ) -> list[tuple[str, str]]:
        pairs = {
            (language.code, translation.to_lang.code)
            for language in languages
            for translation in language.translations_from
            if include_identity or language.code != translation.to_lang.code
        }
        return sorted(pairs)
