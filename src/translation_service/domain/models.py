from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderTranslationRequest:
    text: str
    source_language: str
    target_language: str
    params: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderTranslationResult:
    translation: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supported_pairs: list[tuple[str, str]] | None
    accepts_params: bool


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    ready: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationResult:
    translation: str
    source_language: str
    target_language: str
    translator: str
    metadata: Mapping[str, Any]
