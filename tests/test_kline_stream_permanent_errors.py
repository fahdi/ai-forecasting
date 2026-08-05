"""
Unrecoverable stream rejections (app.services.kline_stream).

On 2026-07-31 Binance began rejecting this host's websocket with HTTP 451
(restricted location). The consumer treated it like a dropped connection and
retried every 5 seconds, at warning level, for three days: the container was
up, the logs looked like ordinary reconnect churn, and market data quietly
stopped. The container only exited three days later.

A 451 will never succeed on retry. The consumer now separates rejections it
cannot recover from, and stops so the process exits nonzero and the container
restart count becomes a visible signal, instead of spinning in silence.
"""

import asyncio

import pytest
from sqlalchemy import create_engine

from app.services.kline_store import create_tables
from app.services.kline_stream import (
    KlineStreamConsumer,
    PermanentStreamRejection,
    is_permanent_rejection,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    create_tables(eng)
    return eng


class FakeRejection(Exception):
    """Stands in for websockets.InvalidStatus, which carries the HTTP status."""

    def __init__(self, status_code, message=None):
        super().__init__(message or f"server rejected WebSocket connection: HTTP {status_code}")
        self.status_code = status_code


class TestClassification:
    @pytest.mark.parametrize("status", [401, 403, 451])
    def test_terminal_rejections_are_permanent(self, status):
        assert is_permanent_rejection(FakeRejection(status)) is True

    @pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
    def test_transient_and_server_errors_are_not_permanent(self, status):
        """Rate limits and server faults do recover; retrying is correct."""
        assert is_permanent_rejection(FakeRejection(status)) is False

    def test_plain_network_errors_are_not_permanent(self):
        assert is_permanent_rejection(ConnectionResetError("reset by peer")) is False
        assert is_permanent_rejection(asyncio.TimeoutError()) is False

    def test_status_is_recognised_from_the_message_when_not_an_attribute(self):
        """The real exception text, for library versions exposing no status."""
        exc = Exception("server rejected WebSocket connection: HTTP 451")
        assert is_permanent_rejection(exc) is True

    def test_unrelated_451_digits_do_not_trigger_a_false_positive(self):
        assert is_permanent_rejection(Exception("read 451 bytes")) is False


@pytest.mark.asyncio
class TestConsumerBehaviour:
    async def test_permanent_rejection_stops_instead_of_retrying(self, engine):
        attempts = []

        async def connect():
            attempts.append(1)
            raise FakeRejection(451)

        consumer = KlineStreamConsumer(
            engine, ["BTCUSDT"], "4h", connect=connect, reconnect_delay=0
        )

        with pytest.raises(PermanentStreamRejection) as exc:
            await consumer.run(max_connections=50)

        # The whole point: it must not have burned 50 reconnects on a 451.
        assert len(attempts) == 1
        assert "451" in str(exc.value)

    async def test_transient_errors_still_reconnect(self, engine):
        """The existing resilience must survive: blips are not fatal."""
        attempts = []

        async def connect():
            attempts.append(1)
            raise ConnectionResetError("reset by peer")

        consumer = KlineStreamConsumer(
            engine, ["BTCUSDT"], "4h", connect=connect, reconnect_delay=0
        )
        await consumer.run(max_connections=3)
        assert len(attempts) == 3


class TestIngestorExitCode:
    """docker's restart count is only a signal if the process actually exits."""

    def _run_main(self, monkeypatch, run_side_effect):
        import scripts.stream_klines as stream_klines

        monkeypatch.setattr(stream_klines, "create_engine", lambda *a, **k: object())
        monkeypatch.setattr(stream_klines, "create_tables", lambda *a, **k: None)

        class FakeConsumer:
            def __init__(self, *a, **k):
                pass

            async def run(self, *a, **k):
                if run_side_effect:
                    raise run_side_effect

        monkeypatch.setattr(stream_klines, "KlineStreamConsumer", FakeConsumer)
        monkeypatch.setattr("sys.argv", ["stream_klines.py", "--interval", "4h"])
        return stream_klines.main()

    def test_permanent_rejection_exits_nonzero(self, monkeypatch, capsys):
        code = self._run_main(monkeypatch, PermanentStreamRejection("HTTP 451"))
        assert code == 2
        stderr = capsys.readouterr().err
        assert "451" in stderr
        assert "restarting will not help" in stderr.lower()

    def test_clean_shutdown_exits_zero(self, monkeypatch):
        assert self._run_main(monkeypatch, None) == 0
