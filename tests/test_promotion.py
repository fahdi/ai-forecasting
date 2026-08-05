"""
The R5 promotion gate (app/models/promotion.py). Issue #21.

R5 says a new model is promoted "only if it beats the incumbent on held-out
data". What registry.promote() actually did was compare two stored
directional_accuracy numbers that came from different walk-forward runs over
different data windows, months apart. In crypto that difference is dominated
by regime, not model quality, so it was not a comparison at all.

It was also strictly-greater with no margin. The live model sits at 0.5238 on
n_test 9328 (models/registry/registry.json), so one standard error is 0.0052:
a candidate at 0.5241 "wins" on nothing. Automating that weekly produces a
random walk of meaningless version changes, which also shreds prediction_log's
per-version accuracy into sample sizes too small to mean anything.

These are pure functions over arrays: no filesystem, no registry, no database.
"""

import math

import numpy as np
import pytest

from app.models.promotion import (
    MIN_ABSOLUTE_ACCURACY,
    MIN_HOLDOUT_ROWS,
    MIN_MARGIN_ABS,
    decide,
    paired_scores,
)

SCHEMA = ["rsi_14", "ema_12_ratio"]


def _window(bars: int) -> int:
    return bars


def _paired(n, candidate_only, incumbent_only, both_correct):
    """Build y/prob arrays with exactly the requested paired counts.

    label 1 means "up". A model is correct when prob > 0.5 matches the label.
    """
    neither = n - candidate_only - incumbent_only - both_correct
    assert neither >= 0
    y, cand, inc = [], [], []

    def add(count, cand_correct, inc_correct):
        for _ in range(count):
            label = 1
            y.append(label)
            cand.append(0.9 if cand_correct else 0.1)
            inc.append(0.9 if inc_correct else 0.1)

    add(both_correct, True, True)
    add(candidate_only, True, False)
    add(incumbent_only, False, True)
    add(neither, False, False)
    return np.array(y), np.array(inc), np.array(cand)


class TestPairedScores:
    def test_counts_discordant_pairs(self):
        y, inc, cand = _paired(n=100, candidate_only=20, incumbent_only=10, both_correct=50)
        result = paired_scores(y, inc, cand)

        assert result.n == 100
        assert result.both_correct == 50
        assert result.candidate_only == 20
        assert result.incumbent_only == 10
        assert result.neither == 20
        assert result.candidate_accuracy == pytest.approx(0.70)
        assert result.incumbent_accuracy == pytest.approx(0.60)
        assert result.diff == pytest.approx(0.10)

    def test_se_diff_is_the_mcnemar_standard_error(self):
        y, inc, cand = _paired(n=1000, candidate_only=40, incumbent_only=30, both_correct=500)
        result = paired_scores(y, inc, cand)
        assert result.se_diff == pytest.approx(math.sqrt(70) / 1000)

    def test_identical_models_have_zero_diff_and_zero_error(self):
        y, inc, cand = _paired(n=200, candidate_only=0, incumbent_only=0, both_correct=120)
        result = paired_scores(y, inc, cand)
        assert result.diff == pytest.approx(0.0)
        assert result.se_diff == pytest.approx(0.0)

    def test_mismatched_array_lengths_raise(self):
        with pytest.raises(ValueError):
            paired_scores(np.array([1, 0]), np.array([0.9]), np.array([0.9, 0.1]))

    def test_empty_arrays_raise_rather_than_dividing_by_zero(self):
        with pytest.raises(ValueError):
            paired_scores(np.array([]), np.array([]), np.array([]))


class TestDecide:
    def _ok(self, **overrides):
        y, inc, cand = _paired(n=2000, candidate_only=120, incumbent_only=40, both_correct=1000)
        base = dict(
            paired=paired_scores(y, inc, cand),
            candidate_schema=SCHEMA,
            incumbent_schema=SCHEMA,
            candidate_window_bars=_window(5000),
            incumbent_window_bars=_window(5000),
        )
        base.update(overrides)
        return base

    def test_margin_above_both_thresholds_promotes(self):
        decision = decide(**self._ok())
        assert decision.promote is True
        assert decision.status == "promoted"

    def test_margin_below_max_of_floor_and_se_rejects(self):
        """The live numbers: 0.5241 vs 0.5238 wins on nothing."""
        y, inc, cand = _paired(n=9328, candidate_only=1500, incumbent_only=1497, both_correct=3390)
        paired = paired_scores(y, inc, cand)
        assert paired.diff < MIN_MARGIN_ABS

        decision = decide(**self._ok(paired=paired))

        assert decision.promote is False
        assert decision.status == "rejected_no_margin"
        assert f"{paired.candidate_accuracy:.4f}" in decision.reason
        assert f"{paired.incumbent_accuracy:.4f}" in decision.reason

    def test_exact_tie_rejects(self):
        """Preserves the conservative behaviour of the old strictly-greater gate."""
        y, inc, cand = _paired(n=2000, candidate_only=50, incumbent_only=50, both_correct=900)
        decision = decide(**self._ok(paired=paired_scores(y, inc, cand)))
        assert decision.promote is False

    def test_holdout_below_min_rows_rejects_regardless_of_margin(self):
        y, inc, cand = _paired(n=100, candidate_only=40, incumbent_only=0, both_correct=40)
        decision = decide(**self._ok(paired=paired_scores(y, inc, cand)))
        assert decision.promote is False
        assert decision.status == "rejected_insufficient_holdout"
        assert "100" in decision.reason
        assert str(MIN_HOLDOUT_ROWS) in decision.reason

    def test_candidate_below_absolute_floor_rejects_even_when_incumbent_is_worse(self):
        """0.49 beating 0.47 is still a coin flip that loses money."""
        y, inc, cand = _paired(n=2000, candidate_only=440, incumbent_only=40, both_correct=540)
        paired = paired_scores(y, inc, cand)
        assert paired.candidate_accuracy < MIN_ABSOLUTE_ACCURACY
        assert paired.diff > MIN_MARGIN_ABS

        decision = decide(**self._ok(paired=paired))

        assert decision.promote is False
        assert decision.status == "rejected_below_floor"

    def test_feature_schema_mismatch_rejects_and_names_the_columns(self):
        decision = decide(**self._ok(candidate_schema=SCHEMA + ["macd_hist"]))
        assert decision.promote is False
        assert decision.status == "rejected_schema_mismatch"
        assert "macd_hist" in decision.reason

    def test_schema_order_does_not_matter(self):
        decision = decide(**self._ok(candidate_schema=list(reversed(SCHEMA))))
        assert decision.status == "promoted"

    def test_shorter_training_window_rejects(self):
        """Guards against a partial backfill winning by accident."""
        decision = decide(**self._ok(candidate_window_bars=_window(2000)))
        assert decision.promote is False
        assert decision.status == "rejected_shorter_window"

    def test_no_incumbent_promotes_when_floors_pass(self):
        y, inc, cand = _paired(n=2000, candidate_only=1200, incumbent_only=0, both_correct=0)
        paired = paired_scores(y, inc, cand)
        decision = decide(
            paired=paired,
            candidate_schema=SCHEMA,
            incumbent_schema=None,
            candidate_window_bars=_window(5000),
            incumbent_window_bars=None,
        )
        assert decision.promote is True
        assert decision.evidence["incumbent_accuracy"] is None

    def test_cold_start_still_respects_the_absolute_floor(self):
        y, inc, cand = _paired(n=2000, candidate_only=800, incumbent_only=0, both_correct=0)
        decision = decide(
            paired=paired_scores(y, inc, cand),
            candidate_schema=SCHEMA,
            incumbent_schema=None,
            candidate_window_bars=_window(5000),
            incumbent_window_bars=None,
        )
        assert decision.promote is False
        assert decision.status == "rejected_below_floor"

    def test_evidence_is_self_contained(self):
        """The audit record must need no other source to be understood."""
        decision = decide(**self._ok())
        for key in (
            "candidate_accuracy",
            "incumbent_accuracy",
            "both_correct",
            "candidate_only",
            "incumbent_only",
            "neither",
            "n",
            "se_diff",
            "threshold",
            "candidate_schema",
            "incumbent_schema",
            "candidate_window_bars",
            "incumbent_window_bars",
        ):
            assert key in decision.evidence, key

    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"candidate_schema": SCHEMA + ["x"]},
            {"candidate_window_bars": 10},
        ],
    )
    def test_no_decision_has_an_empty_reason(self, kwargs):
        decision = decide(**self._ok(**kwargs))
        assert decision.reason.strip()
