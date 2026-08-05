"""
Entry and exit guard evaluation as data rather than control flow (PRD R13).

EnsembleSignalStrategy._entry_allowed was a short-circuit chain of
`return False`, so the only record of why a trade did not happen was a log
line, and only for the first guard that objected. "Why didn't it buy BTC at
14:00?" could not be answered after the fact.

Here every guard is evaluated even after one fails, so the record carries the
whole picture. `reason` still reports the FIRST failing guard in the original
order, so what gets reported and what the strategy does stay in agreement.

Imports stdlib and pandas only - never freqtrade, never I/O - so it runs in
the backend test job as well as the freqtrade one, and so guard logic can
never be the thing that breaks a trade decision.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

ENTRY_REASONS = frozenset(
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

EXIT_REASONS = frozenset({"exit_signal", "hold", "max_hold", "evaluation_error"})

REASONS = ENTRY_REASONS | EXIT_REASONS


@dataclass(frozen=True)
class EntryDecision:
    decision: str  # "entered" | "skipped"
    reason: str
    guards: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExitDecision:
    decision: str  # "exited" | "held"
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)


def _guard(name, passed, value, threshold, note=None) -> Dict[str, Any]:
    entry = {"name": name, "passed": passed, "value": value, "threshold": threshold}
    if note:
        entry["note"] = note
    return entry


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate_entry(
    signal: Optional[Dict[str, Any]],
    close: float,
    ema50: float,
    volatility_ann: float,
    confidence_threshold: float,
    volatility_ceiling: float,
) -> EntryDecision:
    """Evaluate every entry guard and report the first that blocks."""
    has_signal = signal is not None
    not_evaluated = None if has_signal else "not_evaluated"

    # Signal-dependent guards. Absent signal leaves them unevaluated rather
    # than pretending they passed or failed.
    if has_signal:
        stale = bool(signal.get("stale", True))  # absent means stale: fail closed
        direction = signal.get("direction")
        confidence = signal.get("confidence")
        stale_passed = not stale
        direction_passed = direction == "long"
        confidence_passed = _is_number(confidence) and confidence >= confidence_threshold
    else:
        stale = direction = confidence = None
        stale_passed = direction_passed = confidence_passed = None

    # Dataframe-only guards: evaluable with or without a signal.
    trend_passed = not pd.isna(ema50) and close > ema50
    volatility_passed = not pd.isna(volatility_ann) and volatility_ann < volatility_ceiling

    guards = [
        _guard("signal_present", has_signal, has_signal, True),
        _guard("stale", stale_passed, stale, False, not_evaluated),
        _guard("direction", direction_passed, direction, "long", not_evaluated),
        _guard("confidence", confidence_passed, confidence, confidence_threshold, not_evaluated),
        _guard("trend", bool(trend_passed), close, ema50),
        _guard("volatility", bool(volatility_passed), volatility_ann, volatility_ceiling),
    ]

    context = {
        "close": close,
        "ema50": ema50,
        "volatility_ann": volatility_ann,
        "confidence_threshold": confidence_threshold,
        "volatility_ceiling": volatility_ceiling,
        "direction": direction,
        "confidence": confidence,
        "stale": stale,
    }

    # Original short-circuit order, so behaviour and reporting agree.
    if not has_signal:
        reason = "no_signal"
    elif not stale_passed:
        reason = "stale_signal"
    elif not direction_passed:
        reason = "direction_flat"
    elif not confidence_passed:
        reason = "low_confidence"
    elif not trend_passed:
        reason = "trend_guard"
    elif not volatility_passed:
        reason = "volatility_guard"
    else:
        return EntryDecision("entered", "ok", guards, context)

    return EntryDecision("skipped", reason, guards, context)


def evaluate_exit(
    signal: Optional[Dict[str, Any]], exit_confidence_threshold: float
) -> ExitDecision:
    """Exit on a confident flat.

    Deliberately asymmetric with entry: staleness is not checked, because
    getting out is the safe direction and a stale flat should still close a
    position.
    """
    confidence = signal.get("confidence") if signal else None
    context = {
        "direction": signal.get("direction") if signal else None,
        "confidence": confidence,
        "exit_confidence_threshold": exit_confidence_threshold,
    }

    if (
        signal is not None
        and signal.get("direction") == "flat"
        and _is_number(confidence)
        and confidence >= exit_confidence_threshold
    ):
        return ExitDecision("exited", "exit_signal", context)
    return ExitDecision("held", "hold", context)
