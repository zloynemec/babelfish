from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderAnnotationRequest:
    text: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderAnnotationResult:
    annotation: str


@dataclass(frozen=True)
class AnnotatorHealth:
    ready: bool


class AnnotatorProvider(Protocol):
    name: str

    def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult: ...

    def health(self) -> AnnotatorHealth: ...
