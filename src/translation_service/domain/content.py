from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderContentRequest:
    text: str
    params: Mapping[str, Any]


@runtime_checkable
class ContentProvider(Protocol):
    def extract_content(self, request: ProviderContentRequest) -> str: ...
