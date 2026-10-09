from functools import partial
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends

from translation_service.api.dependencies import get_registry, get_settings, get_workers
from translation_service.api.models import (
    LanguagePair,
    TranslatorDescriptor,
    TranslatorListResponse,
)
from translation_service.core.config import Settings
from translation_service.core.workers import WorkerPool
from translation_service.domain.provider import TranslatorProvider
from translation_service.services.registry import TranslatorRegistry

router = APIRouter(prefix="/v1", tags=["translators"])


def _describe_provider(provider: TranslatorProvider) -> TranslatorDescriptor:
    try:
        ready = provider.health().ready
    except Exception:
        ready = False

    try:
        pairs = provider.capabilities().supported_pairs
    except Exception:
        pairs = None

    return TranslatorDescriptor(
        name=TranslatorRegistry.normalize_name(provider.name),
        ready=ready,
        supported_language_pairs=(
            None
            if pairs is None
            else [LanguagePair(source=source, target=target) for source, target in pairs]
        ),
    )


@router.get(
    "/translators",
    response_model=TranslatorListResponse,
    summary="List registered translators",
    operation_id="listTranslators",
)
async def list_translators(
    registry: Annotated[TranslatorRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    workers: Annotated[WorkerPool, Depends(get_workers)],
) -> TranslatorListResponse:
    descriptors: list[TranslatorDescriptor] = []
    for provider in registry.list():
        try:
            with anyio.fail_after(settings.translation_timeout_seconds):
                descriptor = await workers.run(partial(_describe_provider, provider))
        except TimeoutError:
            descriptor = TranslatorDescriptor(
                name=registry.normalize_name(provider.name),
                ready=False,
                supported_language_pairs=None,
            )
        descriptors.append(descriptor)
    return TranslatorListResponse(
        translators=descriptors,
        default_translator=settings.default_translator,
    )
