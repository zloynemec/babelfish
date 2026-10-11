"""Opt-in live title evaluation on the repository's synthetic, non-private corpus."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx

from translation_service.core.config import Settings
from translation_service.main import create_app

ROOT = Path(__file__).resolve().parents[1]


async def evaluate(
    client: httpx.AsyncClient,
    cases: list[dict[str, Any]],
    annotator: str,
    model: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        response = await client.post(
            "/v1/title",
            json={
                "text": case["text"],
                "annotator": annotator,
                "annotator_params": {"model": model},
            },
        )
        body = response.json()
        results.append(
            {
                "id": case["id"],
                "status": response.status_code,
                "expected_status": case["expected_status"],
                "title": body.get("title"),
                "error_code": body.get("error", {}).get("code"),
                "duration_ms": body.get("metadata", {}).get("duration_ms"),
                "criterion": case["criterion"],
                "editor_review": None,
            }
        )
        print(f"{case['id']}: {response.status_code}", flush=True)
        if response.status_code in (503, 504):
            return results
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotator", choices=("iishko", "qwen_local"), default="iishko")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/title-evaluation.json")
    args = parser.parse_args()
    settings = Settings()
    model = args.model or (
        settings.iishko_model if args.annotator == "iishko" else settings.qwen_local_model
    )
    cases = json.loads((ROOT / "tests/fixtures/title_evaluation.json").read_text(encoding="utf-8"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings=settings)), base_url="http://test"
    ) as client:
        results = await evaluate(client, cases, args.annotator, model)
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "annotator": args.annotator,
        "model": model,
        "temperature": 0,
        "max_tokens": 240,
        "max_attempts": 2,
        "timeout_seconds": settings.annotation_timeout_seconds,
        "expected_cases": len(cases),
        "completed_cases": len(results),
        "results": results,
        "editorial_acceptance": "pending",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Report: {args.output}", flush=True)


if __name__ == "__main__":
    anyio.run(main)
