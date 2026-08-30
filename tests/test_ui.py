from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_web_interface_and_static_assets_are_served(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Signal Desk" in page.text
    assert 'id="shorten-form"' in page.text
    assert 'id="admin-form"' in page.text

    stylesheet = client.get("/_assets/styles.css")
    script = client.get("/_assets/app.js")
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]


def test_ui_routes_have_restrictive_headers_without_changing_api(client: TestClient) -> None:
    page = client.get("/")
    asset = client.get("/_assets/app.js")
    api = client.get("/health")

    for response in (page, asset):
        policy = response.headers["content-security-policy"]
        assert "default-src 'self'" in policy
        assert "object-src 'none'" in policy
        assert "frame-ancestors 'none'" in policy
        assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["x-frame-options"] == "DENY"

    assert "content-security-policy" not in api.headers
    assert api.json() == {"status": "ok"}


def test_root_route_does_not_capture_short_code_redirect(client: TestClient) -> None:
    created = client.post("/api/v1/links", json={"url": "https://example.com", "custom_alias": "signal"})
    assert created.status_code == 201

    redirected = client.get("/signal", follow_redirects=False)
    assert redirected.status_code == 307
    assert redirected.headers["location"] == "https://example.com/"


def test_frontend_avoids_persistent_secrets_and_unsafe_html_sinks() -> None:
    script = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text()
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert ".innerHTML" not in script
    assert "X-Admin-Key" in script
    assert "textContent" in script


def test_interface_stays_minimal_and_preserves_interaction_hooks(client: TestClient) -> None:
    page = client.get("/").text
    stylesheet = client.get("/_assets/styles.css").text

    for element_id in (
        "shorten-form",
        "target-url",
        "custom-alias",
        "expires-at",
        "result",
        "admin-form",
        "link-list",
        "disable-dialog",
    ):
        assert f'id="{element_id}"' in page

    assert "hero-notes" not in page
    assert "orbit" not in page
    assert "linear-gradient" not in stylesheet
    assert "radial-gradient" not in stylesheet
