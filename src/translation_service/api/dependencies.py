from fastapi import Request

from translation_service.core.config import Settings
from translation_service.core.workers import WorkerPool
from translation_service.services.annotation import AnnotationService
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.registry import TranslatorRegistry
from translation_service.services.title import TitleService
from translation_service.services.translation import TranslationService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_workers(request: Request) -> WorkerPool:
    return request.app.state.workers


def get_registry(request: Request) -> TranslatorRegistry:
    return request.app.state.registry


def get_translation_service(request: Request) -> TranslationService:
    return request.app.state.translation_service


def get_annotator_registry(request: Request) -> AnnotatorRegistry:
    return request.app.state.annotator_registry


def get_annotation_service(request: Request) -> AnnotationService:
    return request.app.state.annotation_service


def get_title_service(request: Request) -> TitleService:
    return request.app.state.title_service
