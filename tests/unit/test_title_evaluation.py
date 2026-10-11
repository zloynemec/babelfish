import json
from pathlib import Path

import httpx
import pytest

from scripts.evaluate_titles import evaluate


def test_corpus_has_twenty_texts_and_adversarial_cases() -> None:
    cases = json.loads((Path(__file__).parents[1] / "fixtures/title_evaluation.json").read_text())
    assert (
        len([case for case in cases if case["type"] not in ("adversarial", "insufficient")]) >= 20
    )
    assert any(case["type"] == "adversarial" for case in cases)
    assert any(case["expected_status"] == 422 for case in cases)
    assert len({case["id"] for case in cases}) == len(cases)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [200, 503])
async def test_evaluation_records_source_once_and_stops_on_unavailability(status: int) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if status == 503:
            return httpx.Response(503, json={"error": {"code": "annotator_unavailable"}})
        return httpx.Response(200, json={"title": "Title", "metadata": {"duration_ms": 1}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        results = await evaluate(
            client,
            [{"id": "case", "text": "Text", "criterion": "Facts", "expected_status": 200}],
            "iishko",
            "selected",
        )
    assert len(results) == 1
    assert requests[0]["annotator_params"] == {"model": "selected"}
    assert results[0]["editor_review"] is None
    if status == 200:
        assert "target_language" not in requests[0]
        assert "language" not in results[0]
    else:
        assert results[0]["error_code"] == "annotator_unavailable"
