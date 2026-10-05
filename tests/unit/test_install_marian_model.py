from pathlib import Path

from scripts.install_marian_model import parse_args


def test_required_language_arguments_are_parsed() -> None:
    args = parse_args(["--from", "en", "--to", "ru"])

    assert args.source_language == "en"
    assert args.target_language == "ru"
    assert args.model_id is None
    assert args.models_dir is None
    assert args.quantization == "int8"
    assert args.force is False


def test_optional_model_arguments_are_parsed(tmp_path: Path) -> None:
    args = parse_args(
        [
            "--from",
            "de",
            "--to",
            "en",
            "--model-id",
            "example/model",
            "--models-dir",
            str(tmp_path),
            "--quantization",
            "float32",
            "--force",
        ]
    )

    assert args.model_id == "example/model"
    assert args.models_dir == tmp_path
    assert args.quantization == "float32"
    assert args.force is True
