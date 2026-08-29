from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.time_utils import utc_now


def test_create_redirect_and_analytics(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/links",
        json={"url": "https://example.com/articles?id=42", "custom_alias": "article-42"},
    )
    assert created.status_code == 201
    assert created.headers["location"] == "http://testserver/article-42"
    assert created.json()["code"] == "article-42"

    redirected = client.get(
        "/article-42",
        headers={"Referer": "https://search.example/", "User-Agent": "test-agent"},
        follow_redirects=False,
    )
    assert redirected.status_code == 307
    assert redirected.headers["location"] == "https://example.com/articles?id=42"

    analytics = client.get("/api/v1/links/article-42/analytics", headers=admin_headers)
    assert analytics.status_code == 200
    assert analytics.json()["total_clicks"] == 1
    assert analytics.json()["top_referrers"] == [{"referrer": "https://search.example/", "clicks": 1}]


def test_idempotent_create_returns_same_resource(client: TestClient) -> None:
    headers = {"Idempotency-Key": "create-demo-link"}
    first = client.post("/api/v1/links", headers=headers, json={"url": "https://example.com/demo"})
    second = client.post("/api/v1/links", headers=headers, json={"url": "https://example.com/demo"})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["code"] == second.json()["code"]

    conflict = client.post("/api/v1/links", headers=headers, json={"url": "https://example.com/other"})
    assert conflict.status_code == 409


def test_alias_conflict_and_url_validation(client: TestClient) -> None:
    first = client.post("/api/v1/links", json={"url": "https://example.com", "custom_alias": "custom"})
    assert first.status_code == 201
    duplicate = client.post("/api/v1/links", json={"url": "https://openai.com", "custom_alias": "custom"})
    assert duplicate.status_code == 409

    credentials = client.post("/api/v1/links", json={"url": "https://user:secret@example.com/private"})
    assert credentials.status_code == 400
    reserved = client.post("/api/v1/links", json={"url": "https://example.com", "custom_alias": "docs"})
    assert reserved.status_code == 400


def test_expired_and_disabled_links_return_gone(client: TestClient, admin_headers: dict[str, str]) -> None:
    future = (utc_now() + timedelta(seconds=1)).isoformat()
    created = client.post(
        "/api/v1/links",
        json={"url": "https://example.com/temporary", "custom_alias": "temporary", "expires_at": future},
    )
    assert created.status_code == 201

    disabled = client.delete("/api/v1/links/temporary", headers=admin_headers)
    assert disabled.status_code == 204
    response = client.get("/temporary", follow_redirects=False)
    assert response.status_code == 410


def test_admin_endpoints_are_protected(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get("/api/v1/links").status_code == 401
    assert client.get("/api/v1/links", headers=admin_headers).status_code == 200


def test_health_readiness_metrics_and_security_headers(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-request-id"]
    assert client.get("/ready").json() == {"status": "ready"}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "url_shortener_redirects_total" in metrics.text


def test_rate_limit_is_enforced(tmp_path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "limited.db"),
        public_base_url="http://testserver",
        admin_api_key="admin",
        analytics_salt="salt",
        rate_limit_per_minute=1,
    )
    with TestClient(create_app(settings)) as limited:
        assert limited.post("/api/v1/links", json={"url": "https://example.com/one"}).status_code == 201
        assert limited.post("/api/v1/links", json={"url": "https://example.com/two"}).status_code == 429
