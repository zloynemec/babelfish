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
        if request.params:
            raise InvalidAnnotatorParamsError(
                details={"annotator": self.name, "unknown_parameters": sorted(request.params)}
            )
        if not self._api_key:
            raise AnnotatorUnavailableError(details={"annotator": self.name})

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": ANNOTATION_SYSTEM_PROMPT,
                },
                {"role": "user", "content": request.text},
            ],
            "max_tokens": 240,
            "enable_thinking": False,
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
                except (TypeError, ValueError):
                    error_code = None
                if error_code == "Arrearage":
                    raise AnnotatorUnavailableError(details={"annotator": self.name})
            if response.status_code != 200:
                raise AnnotationFailedError(details={"annotator": self.name})
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            return ProviderAnnotationResult(annotation=content.strip())
        except httpx.TimeoutException:
            raise AnnotationTimeoutError(details={"annotator": self.name}) from None
        except httpx.RequestError:
            raise AnnotatorUnavailableError(details={"annotator": self.name}) from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise AnnotationFailedError(details={"annotator": self.name}) from None
