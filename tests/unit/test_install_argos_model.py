from scripts.install_argos_model import parse_args


def test_installer_arguments() -> None:
    args = parse_args(["--from", "en", "--to", "ru"])

    assert args.source_language == "en"
    assert args.target_language == "ru"
    assert args.model_file is None
    assert args.sbd_model_file is None
