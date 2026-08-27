from functools import lru_cache

from pydantic import Field, field_validator
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
    translation_timeout_seconds: float = Field(default=30, gt=0)

    @field_validator("default_translator", "default_source_language")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
