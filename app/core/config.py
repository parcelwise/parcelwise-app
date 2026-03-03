"""Settings, read once from the environment."""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("PARCELWISE_ENV", "dev"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://localhost/parcelwise"))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    shopify_api_version: str = "2026-07"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


settings = Settings()
