"""Qwen3-4B GGUF served locally by llama.cpp's OpenAI-compatible server."""

import httpx

from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotationTimeoutError,
    AnnotatorUnavailableError,
    InvalidAnnotatorParamsError,
)
from translation_service.domain.annotation import (
    AnnotatorHealth,
    ProviderAnnotationRequest,
    ProviderAnnotationResult,
)
from translation_service.providers.annotation_prompt import ANNOTATION_SYSTEM_PROMPT


class QwenLocalProvider:
    name = "qwen_local"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def health(self) -> AnnotatorHealth:
        try:
            with httpx.Client(timeout=2, trust_env=False, transport=self._transport) as client:
                response = client.get(f"{self._base_url.removesuffix('/v1')}/health")
            return AnnotatorHealth(ready=response.status_code == 200)
        except httpx.RequestError:
            return AnnotatorHealth(ready=False)

    def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        if request.params:
            raise InvalidAnnotatorParamsError(
                details={"annotator": self.name, "unknown_parameters": sorted(request.params)}
            )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": ANNOTATION_SYSTEM_PROMPT},
                {"role": "user", "content": request.text},
            ],
            "max_tokens": 240,
            "temperature": 0.2,
        }
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = client.post(f"{self._base_url}/chat/completions", json=payload)
            if response.status_code in (429, 503) or response.status_code >= 500:
                raise AnnotatorUnavailableError(details={"annotator": self.name})
            if response.status_code != 200:
                raise AnnotationFailedError(details={"annotator": self.name})
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            return ProviderAnnotationResult(annotation=content.strip())
        except httpx.TimeoutException:
            raise AnnotationTimeoutError(details={"annotator": self.name}) from None
        except httpx.RequestError:
            raise AnnotatorUnavailableError(details={"annotator": self.name}) from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise AnnotationFailedError(details={"annotator": self.name}) from None
