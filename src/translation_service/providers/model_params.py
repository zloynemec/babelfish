from collections.abc import Mapping
from typing import Any

from translation_service.core.errors import InvalidAnnotatorParamsError


def resolve_model(params: Mapping[str, Any], default: str) -> str:
    unknown = sorted(set(params) - {"model"})
    if unknown:
        raise InvalidAnnotatorParamsError(details={"unknown_parameters": unknown})
    model = params.get("model", default)
    if (
        not isinstance(model, str)
        or not model.strip()
        or len(model) > 200
        or not model.isprintable()
    ):
        raise InvalidAnnotatorParamsError(details={"parameter": "model"})
    return model.strip()
