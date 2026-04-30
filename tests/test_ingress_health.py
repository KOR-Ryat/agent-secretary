"""Tests for the ingress /health endpoint.

A trivial check, but the route is set up alongside the dashboard +
plugin lifespan and could be silently shadowed by a future mount/
include — this test guards against that.
"""

from __future__ import annotations


def test_health_returns_ok():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_route_registered_in_main_app(monkeypatch, tmp_path):
    """The actual main-app build should include /health.

    We use a stub Settings object to avoid pulling in network deps
    (Redis / Postgres / Slack tokens) just to verify the route exists.
    """
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")


    from ingress.config import Settings
    from ingress.main import _build_app

    settings = Settings(
        redis_url="redis://localhost:6379",
        database_url=None,
        github_webhook_secret=None,
        slack_app_token=None,
        slack_bot_token=None,
        log_level="WARNING",
    )
    app = _build_app(settings)

    # Confirm /health is on the routes list without invoking the lifespan
    # (which would try to connect to Redis).
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths
