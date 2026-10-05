#!/usr/bin/env python3
import argparse
import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from translation_service.core.config import Settings
from translation_service.providers.marian import MANIFEST_FILENAME


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and convert a MarianMT model for local CTranslate2 inference.",
    )
    parser.add_argument("--from", dest="source_language", required=True)
    parser.add_argument("--to", dest="target_language", required=True)
    parser.add_argument(
        "--model-id",
        help="Hugging Face model ID or local Transformers model directory.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="Model root; defaults to MARIAN_MODELS_DIR.",
    )
    parser.add_argument(
        "--quantization",
        choices=("int8", "int8_float32", "int16", "float32"),
        default="int8",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing model for this language pair.",
    )
    return parser.parse_args(argv)


def install_model(
    source_language: str,
    target_language: str,
    *,
    model_id: str | None = None,
    models_dir: Path | None = None,
    quantization: str = "int8",
    force: bool = False,
) -> Path:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    from ctranslate2.converters import TransformersConverter
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    source = source_language.strip().lower()
    target = target_language.strip().lower()
    if not source or not target:
        raise SystemExit("Source and target language codes must not be empty")

    resolved_model_id = model_id or f"Helsinki-NLP/opus-mt-{source}-{target}"
    local_model_reference = Path(resolved_model_id).expanduser()
    if local_model_reference.is_dir():
        conversion_source = local_model_reference.resolve()
        model_label = local_model_reference.name
    else:
        print(f"Downloading {resolved_model_id} from Hugging Face...")
        conversion_source = Path(snapshot_download(repo_id=resolved_model_id))
        model_label = resolved_model_id
    resolved_models_dir = (models_dir or Settings().marian_models_dir).expanduser().resolve()
    destination = resolved_models_dir / f"{source}-{target}"

    if destination.exists() and not force:
        raise SystemExit(
            f"Marian model {source} -> {target} already exists; pass --force to replace it"
        )

    resolved_models_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(conversion_source, local_files_only=True)

    with TemporaryDirectory(prefix=f".{source}-{target}-", dir=resolved_models_dir) as temp:
        temporary_root = Path(temp)
        tokenizer_dir = temporary_root / "tokenizer"
        model_dir = temporary_root / "model"
        tokenizer.save_pretrained(tokenizer_dir)

        print(f"Converting {resolved_model_id} to CTranslate2 ({quantization})...")
        converter = TransformersConverter(str(conversion_source))
        converter.convert(str(model_dir), quantization=quantization)

        manifest = {
            "provider": "marian",
            "source_language": source,
            "target_language": target,
            "model_id": model_label,
            "quantization": quantization,
        }
        (temporary_root / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(temporary_root), destination)

    print(f"Installed Marian model {source} -> {target} in {destination}")
    return destination


def main() -> None:
    args = parse_args()
    install_model(
        args.source_language,
        args.target_language,
        model_id=args.model_id,
        models_dir=args.models_dir,
        quantization=args.quantization,
        force=args.force,
    )


if __name__ == "__main__":
    main()
