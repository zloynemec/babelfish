from typing import Annotated

from fastapi import APIRouter, Depends

from translation_service.api.dependencies import (
    get_annotation_service,
    get_annotator_registry,
    get_settings,
)
from translation_service.api.models import (
    ANNOTATION_ERROR_RESPONSES,
    AnnotateRequest,
    AnnotateResponse,
    AnnotatorDescriptor,
    AnnotatorListResponse,
)
from translation_service.core.config import Settings
from translation_service.services.annotation import AnnotationService
from translation_service.services.annotator_registry import AnnotatorRegistry

router = APIRouter(prefix="/v1", tags=["annotation"])


@router.post(
    "/annotate",
    response_model=AnnotateResponse,
    responses=ANNOTATION_ERROR_RESPONSES,
    summary="Annotate content",
    operation_id="annotateContent",
)
async def annotate_content(
    request: AnnotateRequest,
    service: Annotated[AnnotationService, Depends(get_annotation_service)],
) -> AnnotateResponse:
    result = await service.annotate(
        url=request.url,
        html=request.html,
        text=request.text,
        annotator=request.annotator,
        annotator_params=request.annotator_params,
    )
    return AnnotateResponse.model_validate(result)


@router.get(
    "/annotators",
    response_model=AnnotatorListResponse,
    summary="List registered annotators",
    operation_id="listAnnotators",
)
async def list_annotators(
    registry: Annotated[AnnotatorRegistry, Depends(get_annotator_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnnotatorListResponse:
    descriptors: list[AnnotatorDescriptor] = []
    for provider in registry.list():
        try:
            ready = provider.health().ready
        except Exception:
            ready = False
        descriptors.append(
            AnnotatorDescriptor(name=registry.normalize_name(provider.name), ready=ready)
        )
    return AnnotatorListResponse(
        annotators=descriptors, default_annotator=settings.default_annotator
    )
