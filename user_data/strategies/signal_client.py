"""
HTTP client for the ensemble signal API (issue #9, PRD §4.2 R8-R9).

Wraps GET /api/v1/signal/{pair} with a per-(pair, candle) cache so a
backtest or repeated populate_* calls never hammer the API, and a
fail-closed contract: any timeout, connection error, non-200 response, or
unparseable body yields None — never an exception.

Kept separate from the strategy so tests can inject a fake client or a fake
requests session.
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 5.0


class SignalClient:
    """Fetch trade signals, cached per (pair, candle open time)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("SIGNAL_API_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self._cache: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}

    def get_signal(self, pair: str, candle_time: Any) -> Optional[Dict[str, Any]]:
        """Return the signal dict for `pair` at `candle_time`, or None.

        Results — including failures — are cached per (pair, candle) so each
        candle triggers at most one HTTP request per pair.
        """
        key = (pair, str(candle_time))
        if key not in self._cache:
            self._cache[key] = self._fetch(pair)
        return self._cache[key]

    def _fetch(self, pair: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/api/v1/signal/{pair.replace('/', '-')}"
        try:
            response = self.session.get(url, timeout=self.timeout)
        except Exception as exc:  # timeout, DNS, refused connection, ...
            logger.warning("Signal API unreachable for %s (%s): %s", pair, url, exc)
            return None
        if response.status_code != 200:
            logger.warning(
                "Signal API returned %s for %s", response.status_code, pair
            )
            return None
        try:
            return response.json()
        except Exception as exc:
            logger.warning("Signal API returned unparseable body for %s: %s", pair, exc)
            return None
