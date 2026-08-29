from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=str(tmp_path / "test.db"),
        public_base_url="http://testserver",
        admin_api_key="test-admin-key",
        analytics_salt="test-salt",
        rate_limit_per_minute=100,
        cache_ttl_seconds=30,
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": "test-admin-key"}
