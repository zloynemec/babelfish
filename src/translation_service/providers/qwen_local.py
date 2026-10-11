"""Qwen3-4B GGUF served locally by llama.cpp's OpenAI-compatible server."""

import httpx

from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotationTimeoutError,
    AnnotatorUnavailableError,
    InvalidAnnotatorParamsError,
    InvalidTitleError,
)
from translation_service.domain.annotation import (
    AnnotatorHealth,
    ProviderAnnotationRequest,
    ProviderAnnotationResult,
)
from translation_service.domain.title import ProviderTitleRequest, ProviderTitleResult
from translation_service.providers.annotation_prompt import ANNOTATION_SYSTEM_PROMPT
from translation_service.providers.model_params import resolve_model
from translation_service.providers.title_prompt import title_prompt


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
        content = self._complete(request, ANNOTATION_SYSTEM_PROMPT)
        if not content.strip():
            raise AnnotationFailedError(details={"annotator": self.name})
        return ProviderAnnotationResult(annotation=content.strip())

    def title(self, request: ProviderTitleRequest) -> ProviderTitleResult:
        return ProviderTitleResult(title=self._complete(request, title_prompt(request), title=True))

    def _complete(
        self,
        request: ProviderAnnotationRequest | ProviderTitleRequest,
        system_prompt: str,
        *,
        title: bool = False,
    ) -> str:
        model = resolve_model(request.params, self._model)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.text},
            ],
            "max_tokens": 240,
            "temperature": 0 if title else 0.2,
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
            if response.status_code in (400, 404) and "model" in request.params:
                raise InvalidAnnotatorParamsError(details={"parameter": "model"})
            if response.status_code != 200:
                raise AnnotationFailedError(details={"annotator": self.name})
            choice = response.json()["choices"][0]
            if title and choice.get("finish_reason") == "length":
                raise InvalidTitleError()
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("empty content")
            return content
        except httpx.TimeoutException:
            raise AnnotationTimeoutError(details={"annotator": self.name}) from None
        except httpx.RequestError:
            raise AnnotatorUnavailableError(details={"annotator": self.name}) from None
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            if title:
                raise InvalidTitleError() from None
            raise AnnotationFailedError(details={"annotator": self.name}) from None
