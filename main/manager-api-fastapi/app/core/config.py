from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_java_resources() -> Path:
    return Path(__file__).resolve().parents[3] / "manager-api" / "src" / "main" / "resources"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"  # noqa: S104 - container bind is intentional
    port: int = 8002
    context_path: str = "/xiaozhi"
    timezone: str = "Asia/Shanghai"
    database_url: str = "mysql+asyncmy://root:change-me@127.0.0.1:3306/xiaozhi_esp32_server?charset=utf8mb4"
    redis_url: str = "redis://127.0.0.1:6379/0"
    upload_dir: Path = Path("uploadfile")
    java_resources_dir: Path = Field(default_factory=_default_java_resources)
    external_request_timeout_seconds: float = 10.0
    database_pool_size: int = 20
    database_max_overflow: int = 20
    trusted_proxy_count: int = 1
    log_level: str = "INFO"
    server_secret_override: str | None = None
    allow_start_without_dependencies: bool = False
    job_lock_ttl_seconds: int = 120
    graceful_shutdown_seconds: float = 30.0

    @field_validator("context_path")
    @classmethod
    def normalize_context_path(cls, value: str) -> str:
        normalized = "/" + value.strip("/")
        return "" if normalized == "/" else normalized

    @field_validator("database_url")
    @classmethod
    def require_async_driver(cls, value: str) -> str:
        if value.startswith("mysql://"):
            return value.replace("mysql://", "mysql+asyncmy://", 1)
        if value.startswith("sqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value

    @property
    def i18n_dir(self) -> Path:
        return self.java_resources_dir / "i18n"

    @property
    def changelog_path(self) -> Path:
        return self.java_resources_dir / "db" / "changelog" / "db.changelog-master.yaml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
