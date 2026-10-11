from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

INSUFFICIENT_CONTENT = "__INSUFFICIENT_CONTENT__"


@dataclass(frozen=True)
class ProviderTitleRequest:
    text: str
    target_language: str
    params: Mapping[str, Any]
    format_violation: str | None = None


@dataclass(frozen=True)
class ProviderTitleResult:
    title: str


@runtime_checkable
class TitleProvider(Protocol):
    def title(self, request: ProviderTitleRequest) -> ProviderTitleResult: ...
