from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_local_qwen_is_private_and_reachable_from_api() -> None:
    config = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
    model = config["services"]["qwen-local"]
    api = config["services"]["babelfish"]
    assert "ports" not in model
    assert model["networks"] == ["qwen"]
    assert "qwen" in api["networks"]
    assert config["networks"]["qwen"]["internal"] is True
    assert "traefik.enable=false" in model["labels"]
    assert model["user"] == "10001:10001"
    assert model["read_only"] is True
    assert all(volume.endswith(":ro") for volume in model["volumes"])
    assert "@sha256:" in model["image"]
    assert "--log-disable" in model["command"]
    assert "http://qwen-local:8080/v1" in api["environment"]["QWEN_LOCAL_BASE_URL"]


def test_qwen35_weights_aliases_and_thinking_configuration() -> None:
    config = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
    command = config["services"]["qwen-local"]["command"]
    assert command[command.index("--model") + 1] == "/models/Qwen_Qwen3.5-4B-Q5_K_M.gguf"
    assert command[command.index("--alias") + 1] == "qwen3.5-4b,qwen3-4b"
    assert "--jinja" in command
    assert command[command.index("--reasoning") + 1] == "off"
