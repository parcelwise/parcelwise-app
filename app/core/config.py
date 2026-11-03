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
    # Merchant ids allowed to bulk-buy labels (comma separated). Empty means nobody. v1 is Bloom & Co only.
    bulk_labels_merchants: frozenset = field(
        default_factory=lambda: frozenset(m.strip() for m in _env("BULK_LABELS_MERCHANTS").split(",") if m.strip())
    )

    sentry_dsn: str = field(default_factory=lambda: _env("SENTRY_DSN"))
    release: str = field(default_factory=lambda: _env("GIT_SHA", "local"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"


settings = Settings()
