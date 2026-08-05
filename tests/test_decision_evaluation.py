"""
Structured guard evaluation (user_data/strategies/decision.py). Issue #27.

The strategy's entry guards were a short-circuit chain of `return False`, so
the only trace of why a trade did not happen was a log line on a host nobody
reads, and only for the FIRST failing guard. "Why didn't it buy BTC at 14:00?"
was unanswerable after the fact.

This module makes the evaluation data instead of control flow. Every guard is
evaluated even after one fails, so the record shows the whole picture rather
than the first objection, while `reason` preserves the original short-circuit
order so behaviour and reporting still agree.

Deliberately imports nothing from freqtrade, so it runs in the backend job as
well as the strategy job.
"""

import sys
from pathlib import Path

import pytest

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from decision import (  # noqa: E402
    ENTRY_REASONS,
    EXIT_REASONS,
    REASONS,
    evaluate_entry,
    evaluate_exit,
)

CONFIDENCE_THRESHOLD = 0.60
VOLATILITY_CEILING = 1.50


def good_signal(**overrides):
    signal = {
        "pair": "BTC/USDT",
        "direction": "long",
        "confidence": 0.75,
        "stale": False,
    }
    signal.update(overrides)
    return signal


def entry(signal="default", close=110.0, ema50=100.0, volatility_ann=0.80):
    return evaluate_entry(
        signal=good_signal() if signal == "default" else signal,
        close=close,
        ema50=ema50,
        volatility_ann=volatility_ann,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        volatility_ceiling=VOLATILITY_CEILING,
    )


class TestEntryReasons:
    def test_all_guards_passing_enters(self):
        result = entry()
        assert result.decision == "entered"
        assert result.reason == "ok"

    def test_no_signal(self):
        assert entry(signal=None).reason == "no_signal"

    def test_stale_signal(self):
        assert entry(signal=good_signal(stale=True)).reason == "stale_signal"

    def test_missing_stale_field_is_treated_as_stale(self):
        """Fail closed: R9's whole point, and the reason production is safe
        right now with five-day-old klines."""
        signal = good_signal()
        del signal["stale"]
        assert entry(signal=signal).reason == "stale_signal"

    def test_direction_flat(self):
        assert entry(signal=good_signal(direction="flat")).reason == "direction_flat"

    def test_low_confidence(self):
        assert entry(signal=good_signal(confidence=0.10)).reason == "low_confidence"

    @pytest.mark.parametrize("confidence", [None, "high", object()])
    def test_non_numeric_confidence_is_low_confidence_and_does_not_raise(self, confidence):
        assert entry(signal=good_signal(confidence=confidence)).reason == "low_confidence"

    def test_trend_guard(self):
        assert entry(close=90.0, ema50=100.0).reason == "trend_guard"

    def test_nan_ema50_is_trend_guard(self):
        assert entry(ema50=float("nan")).reason == "trend_guard"

    def test_volatility_guard(self):
        assert entry(volatility_ann=9.0).reason == "volatility_guard"

    def test_nan_volatility_is_volatility_guard(self):
        assert entry(volatility_ann=float("nan")).reason == "volatility_guard"

    def test_reason_preserves_the_original_short_circuit_order(self):
        """Stale AND flat AND low confidence reports stale, as before."""
        result = entry(signal=good_signal(stale=True, direction="flat", confidence=0.0))
        assert result.reason == "stale_signal"

    def test_every_blocking_reason_marks_the_decision_skipped(self):
        assert entry(signal=None).decision == "skipped"
        assert entry(volatility_ann=9.0).decision == "skipped"


class TestNonShortCircuitEvaluation:
    def _named(self, result):
        return {g["name"]: g for g in result.guards}

    def test_guards_after_the_failing_one_are_still_evaluated(self):
        """The whole point: the record shows the full picture, not the first
        objection."""
        result = entry(signal=good_signal(confidence=0.10))
        guards = self._named(result)

        assert guards["confidence"]["passed"] is False
        assert guards["trend"]["passed"] is True
        assert guards["trend"]["value"] == 110.0
        assert guards["volatility"]["passed"] is True
        assert guards["volatility"]["value"] == 0.80

    def test_signal_dependent_guards_are_not_evaluated_without_a_signal(self):
        result = entry(signal=None)
        guards = self._named(result)

        for name in ("stale", "direction", "confidence"):
            assert guards[name]["passed"] is None
            assert guards[name]["note"] == "not_evaluated"

        # Dataframe-only guards do not need a signal.
        assert guards["trend"]["passed"] is True
        assert guards["volatility"]["passed"] is True

    def test_every_guard_entry_carries_the_full_schema(self):
        """Schema lock: the JSON contract must not drift silently."""
        for result in (entry(), entry(signal=None), entry(volatility_ann=9.0)):
            for guard in result.guards:
                assert set(guard) >= {"name", "passed", "value", "threshold"}

    def test_context_carries_what_the_decision_was_made_on(self):
        result = entry()
        for key in ("close", "ema50", "volatility_ann", "confidence_threshold", "volatility_ceiling"):
            assert key in result.context


class TestExit:
    def test_confident_flat_exits(self):
        result = evaluate_exit(good_signal(direction="flat", confidence=0.9), 0.5)
        assert result.decision == "exited"
        assert result.reason == "exit_signal"

    def test_low_confidence_flat_holds(self):
        result = evaluate_exit(good_signal(direction="flat", confidence=0.1), 0.5)
        assert result.reason == "hold"

    def test_long_signal_holds(self):
        result = evaluate_exit(good_signal(direction="long", confidence=0.9), 0.5)
        assert result.reason == "hold"

    def test_no_signal_holds(self):
        """Exiting is the safe direction, but an absent signal is not an exit."""
        assert evaluate_exit(None, 0.5).reason == "hold"

    def test_stale_flat_still_exits(self):
        """Deliberate asymmetry with entry: a stale flat still gets you out."""
        result = evaluate_exit(good_signal(direction="flat", confidence=0.9, stale=True), 0.5)
        assert result.reason == "exit_signal"

    @pytest.mark.parametrize("confidence", [None, "x"])
    def test_non_numeric_confidence_holds_and_does_not_raise(self, confidence):
        result = evaluate_exit(good_signal(direction="flat", confidence=confidence), 0.5)
        assert result.reason == "hold"


class TestVocabulary:
    def test_entry_reasons_are_exactly_the_eight(self):
        assert ENTRY_REASONS == frozenset(
            {
                "ok",
                "no_signal",
                "stale_signal",
                "direction_flat",
                "low_confidence",
                "trend_guard",
                "volatility_guard",
                "evaluation_error",
            }
        )

    def test_exit_reasons_are_exactly_the_four(self):
        assert EXIT_REASONS == frozenset({"exit_signal", "hold", "max_hold", "evaluation_error"})

    def test_reasons_is_the_union_and_nothing_else(self):
        assert REASONS == ENTRY_REASONS | EXIT_REASONS

    def test_every_reason_the_module_can_return_is_in_the_vocabulary(self):
        produced = {
            entry().reason,
            entry(signal=None).reason,
            entry(signal=good_signal(stale=True)).reason,
            entry(signal=good_signal(direction="flat")).reason,
            entry(signal=good_signal(confidence=0.1)).reason,
            entry(close=90.0).reason,
            entry(volatility_ann=9.0).reason,
            evaluate_exit(good_signal(direction="flat", confidence=0.9), 0.5).reason,
            evaluate_exit(None, 0.5).reason,
        }
        assert produced <= REASONS


class TestImportability:
    """It must be usable from the backend venv, which has no freqtrade, and it
    must not be able to do I/O in the trading hot path."""

    def _imported_modules(self):
        import ast

        tree = ast.parse((STRATEGY_DIR / "decision.py").read_text())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        return modules

    def test_module_does_not_import_freqtrade(self):
        assert "freqtrade" not in self._imported_modules()

    def test_module_imports_nothing_capable_of_io(self):
        forbidden = {"requests", "httpx", "sqlalchemy", "socket", "urllib", "os", "subprocess"}
        assert not (self._imported_modules() & forbidden)

    def test_module_opens_no_files(self):
        source = (STRATEGY_DIR / "decision.py").read_text()
        assert "open(" not in source
