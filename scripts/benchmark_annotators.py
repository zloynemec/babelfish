"""Reproducible comparison on a shuffled list of public web pages.

Candidates JSON is exported from the supplied XLSX. This script deliberately keeps
the extracted source text identical for both providers and writes progress to disk.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

from translation_service.core.config import Settings
from translation_service.core.errors import (
    AnnotationFailedError,
    AnnotationTimeoutError,
    AnnotatorUnavailableError,
)
from translation_service.domain.annotation import (
    ProviderAnnotationRequest,
    ProviderAnnotationResult,
)
from translation_service.providers.annotation_prompt import ANNOTATION_SYSTEM_PROMPT
from translation_service.providers.iishko import IishkoProvider
from translation_service.providers.qwen_local import QwenLocalProvider
from translation_service.services.content import SafePageFetcher, extract_html_text


def _write_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _fetch(candidate: dict[str, Any]) -> dict[str, Any]:
    fetcher = SafePageFetcher(timeout_seconds=10, max_bytes=2_000_000, dns_server="1.1.1.1")
    try:
        body, content_type = fetcher.fetch(candidate["url"])
        text = extract_html_text(body) if content_type == "text/html" else body
        if len(text.strip()) < 200:
            raise ValueError("less than 200 characters of page text")
        return {**candidate, "text": text[:20_000], "truncated": len(text) > 20_000}
    except Exception as error:
        return {**candidate, "error": type(error).__name__}


def select_sites(candidates_path: Path, output_path: Path, count: int) -> None:
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    selected: list[dict[str, Any]] = []
    attempted: list[dict[str, Any]] = []
    for start in range(0, len(candidates), 20):
        batch = candidates[start : start + 20]
        with ThreadPoolExecutor(max_workers=8) as executor:
            fetched = list(executor.map(_fetch, batch))
        attempted.extend(fetched)
        selected.extend(item for item in fetched if "text" in item)
        print(f"fetch: {len(selected)} usable / {len(attempted)} attempted", flush=True)
        if len(selected) >= count:
            break
    _write_json(output_path, {"selected": selected[:count], "attempted": attempted})
    if len(selected) < count:
        raise RuntimeError(f"only {len(selected)} usable sites found")


class CurlIishkoProvider:
    """Benchmark transport matching the user's working command-line curl path."""

    name = "iishko"

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": ANNOTATION_SYSTEM_PROMPT},
                {"role": "user", "content": request.text},
            ],
            "max_tokens": 240,
            "enable_thinking": False,
        }
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as header_file:
            header_file.write(f"Authorization: Bearer {self._api_key}\n")
            header_file.flush()
            try:
                completed = subprocess.run(
                    [
                        "curl",
                        "--silent",
                        "--show-error",
                        "--max-time",
                        str(self._timeout_seconds),
                        "--header",
                        f"@{header_file.name}",
                        "--header",
                        "Content-Type: application/json",
                        "--data-binary",
                        "@-",
                        "--write-out",
                        "\n%{http_code}",
                        f"{self._base_url}/chat/completions",
                    ],
                    input=json.dumps(payload, ensure_ascii=False),
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_seconds + 5,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise AnnotationTimeoutError(details={"annotator": self.name}) from None
        if completed.returncode != 0:
            raise AnnotatorUnavailableError(details={"annotator": self.name})
        try:
            body_text, status_text = completed.stdout.rsplit("\n", 1)
            status = int(status_text)
            body = json.loads(body_text)
            if status in (401, 403, 429) or status >= 500:
                raise AnnotatorUnavailableError(details={"annotator": self.name})
            if status == 400 and body.get("error", {}).get("code") == "Arrearage":
                raise AnnotatorUnavailableError(details={"annotator": self.name})
            if status != 200:
                raise AnnotationFailedError(details={"annotator": self.name})
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty response")
            return ProviderAnnotationResult(annotation=content.strip())
        except (KeyError, IndexError, TypeError, ValueError):
            raise AnnotationFailedError(details={"annotator": self.name}) from None


def _annotate(
    provider: IishkoProvider | CurlIishkoProvider | QwenLocalProvider, text: str
) -> dict[str, Any]:
    for attempt in range(2):
        started = perf_counter()
        try:
            result = provider.annotate(ProviderAnnotationRequest(text=text, params={}))
            return {"annotation": result.annotation, "seconds": round(perf_counter() - started, 3)}
        except Exception as error:
            failure = {"error": type(error).__name__, "seconds": round(perf_counter() - started, 3)}
            if attempt == 0:
                sleep(2)
    return failure


def _result_line(row: dict[str, Any]) -> str:
    iishko = row["iishko"]
    qwen = row["qwen_local"]
    result = {
        "site": row["url"],
        "iishko_annotation": iishko.get("annotation"),
        "iishko_seconds": iishko.get("seconds"),
        "iishko_error": iishko.get("error"),
        "qwen_annotation": qwen.get("annotation"),
        "qwen_seconds": qwen.get("seconds"),
        "qwen_error": qwen.get("error"),
    }
    return json.dumps(result, ensure_ascii=False)


def run_benchmark(sample_path: Path, output_path: Path) -> None:
    settings = Settings()
    api_key = (
        settings.iishko_api_key.get_secret_value() if settings.iishko_api_key is not None else None
    )
    if not api_key:
        raise RuntimeError("IISHKO_API_KEY must be set in the environment or .env")
    provider_options = {
        "api_key": api_key,
        "base_url": settings.iishko_base_url,
        "model": settings.iishko_model,
        "timeout_seconds": max(180, settings.annotation_provider_timeout_seconds),
    }
    iishko: IishkoProvider | CurlIishkoProvider = IishkoProvider(**provider_options)
    qwen = QwenLocalProvider(
        base_url=settings.qwen_local_base_url,
        model=settings.qwen_local_model,
        timeout_seconds=max(180, settings.annotation_provider_timeout_seconds),
    )
    sample = json.loads(sample_path.read_text(encoding="utf-8"))["selected"]
    results: list[dict[str, Any]] = [
        {
            "rank": item["rank"],
            "domain": item["domain"],
            "url": item["url"],
            "text": item["text"],
            "truncated": item["truncated"],
        }
        for item in sample
    ]
    if output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        for index, row in enumerate(previous):
            if index < len(results) and row["url"] == results[index]["url"]:
                results[index].update(row)
    emitted: set[int] = set()
    for index, row in enumerate(results):
        if "iishko" in row and "qwen_local" in row:
            print(_result_line(row), flush=True)
            emitted.add(index)
    jobs: list[tuple[int, str]] = []
    for index, row in enumerate(results):
        for name in ("iishko", "qwen_local"):
            if name not in row:
                jobs.append((index, name))
    if any(name == "qwen_local" for _, name in jobs) and not qwen.health().ready:
        raise RuntimeError("local Qwen server is not ready")
    if any(name == "iishko" for _, name in jobs):
        preflight = ProviderAnnotationRequest(text="Привет. Проверка доступа.", params={})
        try:
            iishko.annotate(preflight)
            print("iishko preflight: ok (httpx)", file=sys.stderr, flush=True)
        except (AnnotatorUnavailableError, AnnotationTimeoutError):
            iishko = CurlIishkoProvider(**provider_options)
            iishko.annotate(preflight)
            print("iishko preflight: ok (curl)", file=sys.stderr, flush=True)
    with (
        ThreadPoolExecutor(max_workers=4) as cloud_pool,
        ThreadPoolExecutor(max_workers=2) as local_pool,
    ):
        futures = {}
        for index, name in jobs:
            pool = cloud_pool if name == "iishko" else local_pool
            provider = iishko if name == "iishko" else qwen
            future = pool.submit(_annotate, provider, results[index]["text"])
            futures[future] = (index, name)
        for completed, future in enumerate(as_completed(futures), start=1):
            index, name = futures[future]
            results[index][name] = future.result()
            _write_json(output_path, results)
            if (
                index not in emitted
                and "iishko" in results[index]
                and "qwen_local" in results[index]
            ):
                print(_result_line(results[index]), flush=True)
                emitted.add(index)
            print(
                f"annotation: {completed}/{len(jobs)} {results[index]['domain']} {name}",
                file=sys.stderr,
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("select", "run"))
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()
    if args.mode == "select":
        if args.candidates is None:
            parser.error("--candidates is required for select")
        select_sites(args.candidates, args.sample, args.count)
    else:
        if args.results is None:
            parser.error("--results is required for run")
        run_benchmark(args.sample, args.results)
