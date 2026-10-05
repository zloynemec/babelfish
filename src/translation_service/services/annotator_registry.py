from translation_service.core.errors import UnknownAnnotatorError
from translation_service.domain.annotation import AnnotatorProvider


class DuplicateAnnotatorError(ValueError):
    pass


class AnnotatorRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AnnotatorProvider] = {}

    @staticmethod
    def normalize_name(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("annotator name must not be empty")
        return normalized

    def register(self, provider: AnnotatorProvider) -> None:
        name = self.normalize_name(provider.name)
        if name in self._providers:
            raise DuplicateAnnotatorError(f"annotator {name!r} is already registered")
        self._providers[name] = provider

    def get(self, name: str) -> AnnotatorProvider:
        normalized = self.normalize_name(name)
        try:
            return self._providers[normalized]
        except KeyError:
            raise UnknownAnnotatorError(details={"annotator": normalized}) from None

    def list(self) -> list[AnnotatorProvider]:
        return list(self._providers.values())
