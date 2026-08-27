from translation_service.core.errors import UnknownTranslatorError
from translation_service.domain.provider import TranslatorProvider


class DuplicateTranslatorError(ValueError):
    """Raised when a provider name is registered more than once."""


class TranslatorRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TranslatorProvider] = {}

    @staticmethod
    def normalize_name(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("translator name must not be empty")
        return normalized

    def register(self, provider: TranslatorProvider) -> None:
        name = self.normalize_name(provider.name)
        if name in self._providers:
            raise DuplicateTranslatorError(f"translator {name!r} is already registered")
        self._providers[name] = provider

    def get(self, name: str) -> TranslatorProvider:
        normalized = self.normalize_name(name)
        try:
            return self._providers[normalized]
        except KeyError:
            raise UnknownTranslatorError(details={"translator": normalized}) from None

    def exists(self, name: str) -> bool:
        try:
            normalized = self.normalize_name(name)
        except ValueError:
            return False
        return normalized in self._providers

    def list(self) -> list[TranslatorProvider]:
        return list(self._providers.values())
