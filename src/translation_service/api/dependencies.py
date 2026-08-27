from fastapi import Request

from translation_service.core.config import Settings
from translation_service.services.registry import TranslatorRegistry
from translation_service.services.translation import TranslationService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> TranslatorRegistry:
    return request.app.state.registry


def get_translation_service(request: Request) -> TranslationService:
    return request.app.state.translation_service
