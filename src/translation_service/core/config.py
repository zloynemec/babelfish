import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    default_translator: str = "argos"
    default_source_language: str = "en"
    max_text_length: int = Field(default=20_000, ge=1)
    max_request_body_bytes: int = Field(default=16_000_000, ge=1)
    max_concurrent_operations: int = Field(default=4, ge=1)
    translation_timeout_seconds: float = Field(default=30, gt=0)
    marian_models_dir: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "share" / "babelfish" / "marian"
    )
    marian_device: Literal["cpu", "cuda", "auto"] = "cpu"
    marian_compute_type: str = "int8"
    default_annotator: str = "iishko"
    iishko_api_key: SecretStr | None = None
    iishko_base_url: str = "https://api.reformboss.com/v1"
    iishko_model: str = "qwen3.8-flash"
    qwen_local_base_url: str = "http://127.0.0.1:8081/v1"
    qwen_local_model: str = "qwen3-4b"
    annotation_max_input_chars: int = Field(default=2_000_000, ge=1)
    annotation_max_text_chars: int = Field(default=20_000, ge=1)
    annotation_max_download_bytes: int = Field(default=2_000_000, ge=1)
    annotation_fetch_timeout_seconds: float = Field(default=10, gt=0)
    annotation_dns_server: str | None = None
    annotation_provider_timeout_seconds: float = Field(default=90, gt=0)
    annotation_timeout_seconds: float = Field(default=100, gt=0)

    @field_validator("default_translator", "default_source_language", "default_annotator")
    @classmethod
    def normalize_lowercase_setting(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("marian_models_dir", mode="before")
    @classmethod
    def expand_marian_models_dir(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @field_validator("marian_compute_type")
    @classmethod
    def normalize_compute_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("annotation_dns_server", mode="before")
    @classmethod
    def normalize_dns_server(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        address = ipaddress.ip_address(value.strip())
        if not address.is_global:
            raise ValueError("annotation DNS server must have a public IP address")
        return str(address)


@lru_cache
def get_settings() -> Settings:
    return Settings()
