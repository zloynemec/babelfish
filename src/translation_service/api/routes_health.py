from collections.abc import Callable
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Response

from translation_service.api.dependencies import (
    get_annotator_registry,
    get_iishko_health,
    get_registry,
    get_settings,
    get_workers,
)
from translation_service.api.models import (
    AnnotatorDescriptor,
    HealthChecks,
    HealthResponse,
    TranslatorHealth,
)
from translation_service.core.config import Settings
from translation_service.core.workers import WorkerPool
from translation_service.domain.annotation import AnnotatorHealth
from translation_service.domain.models import ProviderHealth
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.iishko_health import IishkoHealthCheck
from translation_service.services.registry import TranslatorRegistry

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Default translator is unavailable"}},
    summary="Check service health",
    description=(
        "Reports liveness, readiness for every registered translator and annotator, "
        "and a cached Iishko annotation probe. "
        "If the default translator is ready but the Iishko probe fails, the response is 200 "
        "with status degraded. "
        "If the default translator fails, the HTTP response is 503 with all check results."
    ),
    operation_id="health",
)
async def health(
    response: Response,
    registry: Annotated[TranslatorRegistry, Depends(get_registry)],
    annotator_registry: Annotated[AnnotatorRegistry, Depends(get_annotator_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    workers: Annotated[WorkerPool, Depends(get_workers)],
    iishko: Annotated[IishkoHealthCheck, Depends(get_iishko_health)],
) -> HealthResponse:
    translators = {registry.normalize_name(provider.name): provider for provider in registry.list()}
    annotators = {
        annotator_registry.normalize_name(provider.name): provider
        for provider in annotator_registry.list()
    }
    translator_states = dict.fromkeys(translators, False)
    annotator_states = dict.fromkeys(annotators, False)
    default = settings.default_translator
    iishko_ready = False

    async def check_provider(
        states: dict[str, bool],
        name: str,
        probe: Callable[[], ProviderHealth | AnnotatorHealth],
    ) -> None:
        try:
            with anyio.fail_after(settings.translation_timeout_seconds):
                states[name] = (await workers.run(probe)).ready
        except Exception:
            states[name] = False

    async def check_iishko() -> None:
        nonlocal iishko_ready
        iishko_ready = await iishko.is_healthy()

    async with anyio.create_task_group() as group:
        if default in translators:
            group.start_soon(
                check_provider, translator_states, default, translators[default].health
            )
        group.start_soon(check_iishko)
        for name, translator in translators.items():
            if name != default:
                group.start_soon(check_provider, translator_states, name, translator.health)
        for name, annotator in annotators.items():
            if name != "iishko":
                group.start_soon(check_provider, annotator_states, name, annotator.health)

    if "iishko" in annotator_states:
        annotator_states["iishko"] = iishko_ready
    translator_ready = translator_states.get(default, False)

    if not translator_ready:
        response.status_code = 503
    return HealthResponse(
        status=("ok" if iishko_ready else "degraded") if translator_ready else "not_ready",
        checks=HealthChecks(
            live=True,
            translator=TranslatorHealth(name=default, ready=translator_ready),
            iishko=iishko_ready,
            translators=[
                TranslatorHealth(name=name, ready=ready)
                for name, ready in translator_states.items()
            ],
            annotators=[
                AnnotatorDescriptor(name=name, ready=ready)
                for name, ready in annotator_states.items()
            ],
        ),
    )
