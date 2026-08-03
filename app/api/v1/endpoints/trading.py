"""
Trading state: unified view of the live execution engine (freqtrade).

The platform API is the single surface the dashboard talks to; this module
proxies freqtrade's REST API (token login, then status/profit/show_config)
and fails closed: 503 when the bot is unreachable, 502 when it misbehaves.
"""

import os
from typing import Any, Dict, Iterator

import httpx
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


def get_freqtrade_client() -> Iterator[httpx.Client]:
    """HTTP client for the freqtrade REST API (overridden in tests)."""
    base_url = os.environ.get("FREQTRADE_API_URL", "http://freqtrade:8080")
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        yield client


@router.get("/summary")
def trading_summary(
    client: httpx.Client = Depends(get_freqtrade_client),
) -> Dict[str, Any]:
    """Bot state, open trades, and profit in one payload."""
    username = os.environ.get("FREQTRADE_API_USERNAME", "freqtrader")
    password = os.environ.get("FREQTRADE_API_PASSWORD", "")

    try:
        login = client.post("/api/v1/token/login", auth=(username, password))
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail=f"Freqtrade unreachable: {exc}"
        ) from exc
    if login.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Freqtrade authentication failed (HTTP {login.status_code})",
        )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    try:
        status = client.get("/api/v1/status", headers=headers)
        profit = client.get("/api/v1/profit", headers=headers)
        config = client.get("/api/v1/show_config", headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail=f"Freqtrade unreachable: {exc}"
        ) from exc
    for resp in (status, profit, config):
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Freqtrade error on {resp.request.url.path} "
                f"(HTTP {resp.status_code})",
            )

    open_trades = status.json()
    config_data = config.json()
    return {
        "state": config_data.get("state"),
        "dry_run": config_data.get("dry_run"),
        "open_trades": open_trades,
        "open_trade_count": len(open_trades),
        "profit": profit.json(),
    }
