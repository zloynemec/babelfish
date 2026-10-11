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


class IishkoProvider:
    name = "iishko"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def health(self) -> AnnotatorHealth:
        return AnnotatorHealth(ready=bool(self._api_key))

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
        if not self._api_key:
            raise AnnotatorUnavailableError(details={"annotator": self.name})

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": request.text},
            ],
            "max_tokens": 240,
            "enable_thinking": False,
            **({"temperature": 0} if title else {}),
        }
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                trust_env=True,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
            if response.status_code in (401, 403, 429) or response.status_code >= 500:
                raise AnnotatorUnavailableError(details={"annotator": self.name})
            if response.status_code == 400:
                try:
                    error_code = response.json().get("error", {}).get("code")
                except (AttributeError, TypeError, ValueError):
                    error_code = None
                if error_code == "Arrearage":
                    raise AnnotatorUnavailableError(details={"annotator": self.name})
            if response.status_code in (400, 404) and "model" in request.params:
                raise InvalidAnnotatorParamsError(details={"parameter": "model"})
            if response.status_code != 200:
                raise AnnotationFailedError(details={"annotator": self.name})
            body = response.json()
            choice = body["choices"][0]
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
