from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    database_path: str = "data/url-shortener.db"
    public_base_url: str = "http://localhost:8000"
    admin_api_key: str = "change-me"
    analytics_salt: str = "development-only-salt"
    rate_limit_per_minute: int = 120
    cache_ttl_seconds: int = 30

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            database_path=os.getenv("DATABASE_PATH", "data/url-shortener.db"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            admin_api_key=os.getenv("ADMIN_API_KEY", "change-me"),
            analytics_salt=os.getenv("ANALYTICS_SALT", "development-only-salt"),
            rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "120")),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "30")),
        )

    def validate(self) -> None:
        if self.app_env == "production" and self.admin_api_key.startswith("change-me"):
            raise RuntimeError("ADMIN_API_KEY must be changed in production")
        if self.app_env == "production" and self.analytics_salt.startswith("change-me"):
            raise RuntimeError("ANALYTICS_SALT must be changed in production")
        if self.rate_limit_per_minute < 1:
            raise RuntimeError("RATE_LIMIT_PER_MINUTE must be positive")
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
