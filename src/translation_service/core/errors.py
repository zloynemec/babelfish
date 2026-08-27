from collections.abc import Mapping
from typing import Any


class ApplicationError(Exception):
    """A safe, public application error."""

    code = "application_error"
    status_code = 500
    default_message = "Application error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = dict(details or {})
        super().__init__(self.message)


class InvalidRequestError(ApplicationError):
    code = "invalid_request"
    status_code = 400
    default_message = "Request is invalid"


class TextTooLargeError(ApplicationError):
    code = "text_too_large"
    status_code = 413
    default_message = "Text exceeds the configured maximum length"


class UnknownTranslatorError(ApplicationError):
    code = "unknown_translator"
    status_code = 404
    default_message = "Translator is not registered"


class InvalidTranslatorParamsError(ApplicationError):
    code = "invalid_translator_params"
    status_code = 422
    default_message = "Translator parameters are invalid"


class UnsupportedLanguagePairError(ApplicationError):
    code = "unsupported_language_pair"
    status_code = 422
    default_message = "Translator does not support requested language pair"


class TranslatorUnavailableError(ApplicationError):
    code = "translator_unavailable"
    status_code = 503
    default_message = "Translator is not ready"


class TranslationTimeoutError(ApplicationError):
    code = "translation_timeout"
    status_code = 504
    default_message = "Translation timed out"


class TranslationFailedError(ApplicationError):
    code = "translation_failed"
    status_code = 500
    default_message = "Translation failed"
