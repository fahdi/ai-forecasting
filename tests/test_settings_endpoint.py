"""
GET /api/v1/settings — read-only, safe-to-display runtime configuration for
the dashboard Settings tab. Must never leak secrets (API keys, DSNs, DB URLs).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_settings_returns_safe_config():
    response = client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["rate_limit_per_minute"] > 0
    assert body["rate_limit_per_hour"] > 0
    assert body["default_forecast_horizon"] >= 1
    assert body["max_forecast_horizon"] >= body["default_forecast_horizon"]
    assert isinstance(body["yahoo_finance_enabled"], bool)
    assert isinstance(body["alpha_vantage_enabled"], bool)
    assert body["version"]


def test_settings_never_exposes_secrets():
    body = client.get("/api/v1/settings").json()
    flattened = str(body).lower()
    for needle in ("secret", "password", "api_key", "dsn", "postgresql://", "redis://"):
        assert needle not in flattened
