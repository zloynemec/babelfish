from typing import Annotated

from fastapi import APIRouter, Depends

from translation_service.api.dependencies import get_content_service
from translation_service.api.models import (
    ContentRequest,
    ContentResponse,
    ErrorEnvelope,
)
from translation_service.services.extraction import ContentService

router = APIRouter(prefix="/v1", tags=["content"])


@router.post(
    "/content",
    response_model=ContentResponse,
    responses={
        status: {"model": ErrorEnvelope} for status in (400, 403, 404, 413, 415, 422, 502, 503, 504)
    },
    summary="Extract page content",
    description=(
        "Send exactly one of `url` (public URL), `html` (raw HTML), or `text` (plain text). "
        "The service removes navigation, standalone contact forms, and other boilerplate, "
        "then returns the original headings, paragraphs, lists, and table rows in `content` "
        "in source order. Long pages are processed in batches. A successful response contains "
        "the complete cleaned text, with `metadata.truncated` set to `false`. "
        "Use `annotator` or `annotator_params.model` to select the provider or model."
    ),
    operation_id="extractContent",
)
async def extract_content(
    request: ContentRequest,
    service: Annotated[ContentService, Depends(get_content_service)],
) -> ContentResponse:
    result = await service.extract_content(
        url=request.url,
        html=request.html,
        text=request.text,
        annotator=request.annotator,
        annotator_params=request.annotator_params,
    )
    return ContentResponse.model_validate(result)
