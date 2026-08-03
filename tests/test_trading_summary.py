"""
TDD for GET /api/v1/trading/summary: the platform's unified view of the
live execution engine (freqtrade REST API).

Contract:
- 200 with {"state", "open_trades", "open_trade_count", "profit"} when the
  bot responds
- 503 when freqtrade is unreachable (connection error): the platform must
  fail closed, not hang or 500
- 502 when freqtrade rejects our credentials or returns a non-200

No network: freqtrade is simulated with httpx.MockTransport via the
get_freqtrade_client dependency override.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.endpoints.trading import get_freqtrade_client

client = TestClient(app)

OPEN_TRADES = [
    {"trade_id": 1, "pair": "BTC/USDT", "stake_amount": 330.0, "profit_abs": 1.2},
    {"trade_id": 2, "pair": "ETH/USDT", "stake_amount": 330.0, "profit_abs": -0.4},
]
PROFIT = {"profit_closed_coin": 3.5, "profit_all_percent_mean": 0.8, "trade_count": 7}


def _override_with(handler):
    transport = httpx.MockTransport(handler)

    def _client():
        with httpx.Client(
            transport=transport, base_url="http://freqtrade:8080"
        ) as fake:
            yield fake

    app.dependency_overrides[get_freqtrade_client] = _client


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.pop(get_freqtrade_client, None)


def _happy_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/token/login":
        assert request.method == "POST"
        return httpx.Response(200, json={"access_token": "tok123"})
    assert request.headers["Authorization"] == "Bearer tok123"
    if request.url.path == "/api/v1/status":
        return httpx.Response(200, json=OPEN_TRADES)
    if request.url.path == "/api/v1/profit":
        return httpx.Response(200, json=PROFIT)
    if request.url.path == "/api/v1/show_config":
        return httpx.Response(200, json={"state": "running", "dry_run": True})
    raise AssertionError(f"unexpected path {request.url.path}")


def test_summary_success_returns_unified_payload():
    _override_with(_happy_handler)
    resp = client.get("/api/v1/trading/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "running"
    assert data["dry_run"] is True
    assert data["open_trade_count"] == 2
    assert data["open_trades"] == OPEN_TRADES
    assert data["profit"] == PROFIT


def test_summary_bot_unreachable_returns_503():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _override_with(handler)
    resp = client.get("/api/v1/trading/summary")
    assert resp.status_code == 503
    assert "unreachable" in resp.json()["detail"].lower()


def test_summary_bad_credentials_returns_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"})

    _override_with(handler)
    resp = client.get("/api/v1/trading/summary")
    assert resp.status_code == 502
    assert "authentication" in resp.json()["detail"].lower()


def test_summary_bot_error_after_login_returns_502():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/token/login":
            return httpx.Response(200, json={"access_token": "tok123"})
        return httpx.Response(500, json={"detail": "boom"})

    _override_with(handler)
    resp = client.get("/api/v1/trading/summary")
    assert resp.status_code == 502


def test_summary_connection_drops_after_login_returns_503():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/token/login":
            return httpx.Response(200, json={"access_token": "tok123"})
        raise httpx.ReadTimeout("timed out", request=request)

    _override_with(handler)
    resp = client.get("/api/v1/trading/summary")
    assert resp.status_code == 503


def test_default_client_uses_env_configuration(monkeypatch):
    monkeypatch.setenv("FREQTRADE_API_URL", "http://example.invalid:9")
    gen = get_freqtrade_client()
    real = next(gen)
    assert str(real.base_url) == "http://example.invalid:9"
    gen.close()


def test_route_is_registered():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/trading/summary" in paths
