#!/usr/bin/env python3
import argparse
from collections.abc import Sequence
from pathlib import Path
from shutil import copy2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly install an Argos Translate language model.",
    )
    parser.add_argument("--from", dest="source_language", required=True)
    parser.add_argument("--to", dest="target_language", required=True)
    parser.add_argument(
        "--model-file",
        type=Path,
        help="Install a local .argosmodel file instead of downloading from the index.",
    )
    parser.add_argument(
        "--sbd-model-file",
        type=Path,
        help="Local MiniSBD .onnx file; required for a fully local first install.",
    )
    return parser.parse_args(argv)


def _install_minisbd_model(
    source_language: str,
    model_file: Path | None,
    *,
    allow_download: bool,
) -> None:
    from argostranslate import sbd

    model_code = sbd.MiniSBDSentencizer.LANGUAGE_CODE_MAPPING.get(source_language, source_language)
    if model_code not in sbd.minisbd_models.MODELS:
        model_code = "en"
    model_filename = sbd.minisbd_models.MODELS[model_code]
    destination = Path(sbd.minisbd_models.cache_dir) / model_filename
    if destination.is_file():
        print(f"MiniSBD model {model_code} is already installed")
        return

    if model_file is not None:
        if not model_file.is_file():
            raise SystemExit(f"MiniSBD model file does not exist: {model_file}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(model_file, destination)
        print(f"Installed MiniSBD model {model_code} from {model_file}")
        return

    if not allow_download:
        raise SystemExit(
            "MiniSBD model is missing; pass --sbd-model-file for a fully local install"
        )

    print(f"Downloading MiniSBD model {model_code}...")
    sbd.minisbd_models.download_models(load_only=[model_code])
    print(f"Installed MiniSBD model {model_code}")


def install_model(
    source_language: str,
    target_language: str,
    model_file: Path | None = None,
    sbd_model_file: Path | None = None,
) -> None:
    from argostranslate import package as argos_package

    source = source_language.strip().lower()
    target = target_language.strip().lower()
    if not source or not target:
        raise SystemExit("Source and target language codes must not be empty")

    if model_file is not None:
        if not model_file.is_file():
            raise SystemExit(f"Model file does not exist: {model_file}")
        argos_package.install_from_path(model_file)
        print(f"Installed Argos model {source} -> {target} from {model_file}")
    else:
        installed = argos_package.get_installed_packages()
        if any(package.from_code == source and package.to_code == target for package in installed):
            print(f"Argos model {source} -> {target} is already installed")
        else:
            print("Updating the Argos package index...")
            argos_package.update_package_index()
            matching_packages = [
                package
                for package in argos_package.get_available_packages()
                if package.from_code == source and package.to_code == target
            ]
            if not matching_packages:
                raise SystemExit(f"No Argos model found for {source} -> {target}")

            selected_package = matching_packages[0]
            print(f"Downloading Argos model {source} -> {target}...")
            package_path = selected_package.download()
            argos_package.install_from_path(package_path)
            print(f"Installed Argos model {source} -> {target}")

    _install_minisbd_model(
        source,
        sbd_model_file,
        allow_download=model_file is None,
    )


def main() -> None:
    args = parse_args()
    install_model(
        args.source_language,
        args.target_language,
        args.model_file,
        args.sbd_model_file,
    )


if __name__ == "__main__":
    main()
