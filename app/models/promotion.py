"""
The R5 promotion gate: does the candidate actually beat the incumbent?

registry.promote() used to compare two stored directional_accuracy numbers
that came from different walk-forward runs over different data windows, months
apart. In crypto that difference is dominated by regime, not model quality, so
it was not a comparison. It was also strictly-greater with no margin: with the
live model at 0.5238 on n_test 9328, one standard error is 0.0052, so a
candidate at 0.5241 wins on noise. Automating that weekly produces a random
walk of meaningless version changes and shreds prediction_log's per-version
accuracy into useless sample sizes.

Everything here is a pure function over arrays: both models are scored on the
SAME held-out rows, and the decision carries enough evidence to be audited
without consulting anything else.

Known limitation, recorded rather than papered over: the pooled training set
stacks four pairs sharing timestamps, so `n` overstates independence by roughly
4x and `se_diff` is correspondingly optimistic. MIN_ABSOLUTE_ACCURACY partially
covers it. Do not inflate the margin without evidence; the run ledger will
supply that evidence.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# A candidate needs at least this many held-out rows before its score means
# anything at all.
MIN_HOLDOUT_ROWS = 500
# Below this the model is a coin flip, however bad the incumbent is.
MIN_ABSOLUTE_ACCURACY = 0.50
# Floor on the improvement, on top of the statistical margin.
MIN_MARGIN_ABS = 0.005


@dataclass(frozen=True)
class PairedResult:
    n: int
    both_correct: int
    candidate_only: int
    incumbent_only: int
    neither: int
    candidate_accuracy: float
    incumbent_accuracy: float
    diff: float
    se_diff: float


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    status: str
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)


def _correct(y_true: Sequence, prob: Sequence) -> List[bool]:
    return [(p > 0.5) == bool(label) for label, p in zip(y_true, prob)]


def paired_scores(
    y_true: Sequence, prob_incumbent: Sequence, prob_candidate: Sequence
) -> PairedResult:
    """Score both models on the same rows and count the discordant pairs.

    se_diff is the McNemar standard error of the paired accuracy difference,
    which depends only on the rows where the two models disagree. Rows they
    both get right (or both get wrong) carry no information about which is
    better, which is exactly why an unpaired comparison is so noisy.
    """
    n = len(y_true)
    if not (n == len(prob_incumbent) == len(prob_candidate)):
        raise ValueError("y_true, prob_incumbent and prob_candidate must be the same length")
    if n == 0:
        raise ValueError("cannot score an empty holdout")

    incumbent_correct = _correct(y_true, prob_incumbent)
    candidate_correct = _correct(y_true, prob_candidate)

    both = sum(1 for c, i in zip(candidate_correct, incumbent_correct) if c and i)
    candidate_only = sum(1 for c, i in zip(candidate_correct, incumbent_correct) if c and not i)
    incumbent_only = sum(1 for c, i in zip(candidate_correct, incumbent_correct) if i and not c)
    neither = n - both - candidate_only - incumbent_only

    candidate_accuracy = (both + candidate_only) / n
    incumbent_accuracy = (both + incumbent_only) / n

    return PairedResult(
        n=n,
        both_correct=both,
        candidate_only=candidate_only,
        incumbent_only=incumbent_only,
        neither=neither,
        candidate_accuracy=candidate_accuracy,
        incumbent_accuracy=incumbent_accuracy,
        diff=candidate_accuracy - incumbent_accuracy,
        se_diff=math.sqrt(candidate_only + incumbent_only) / n,
    )


def decide(
    paired: PairedResult,
    candidate_schema: Sequence[str],
    incumbent_schema: Optional[Sequence[str]],
    candidate_window_bars: Optional[int],
    incumbent_window_bars: Optional[int],
) -> PromotionDecision:
    """Promote only when every guard passes. Cold start (no incumbent) still
    has to clear the holdout size and the absolute accuracy floor."""
    cold_start = incumbent_schema is None
    threshold = max(MIN_MARGIN_ABS, paired.se_diff)

    evidence = {
        "candidate_accuracy": paired.candidate_accuracy,
        "incumbent_accuracy": None if cold_start else paired.incumbent_accuracy,
        "both_correct": paired.both_correct,
        "candidate_only": paired.candidate_only,
        "incumbent_only": paired.incumbent_only,
        "neither": paired.neither,
        "n": paired.n,
        "diff": paired.diff,
        "se_diff": paired.se_diff,
        "threshold": threshold,
        "candidate_schema": list(candidate_schema),
        "incumbent_schema": None if cold_start else list(incumbent_schema),
        "candidate_window_bars": candidate_window_bars,
        "incumbent_window_bars": incumbent_window_bars,
    }

    def reject(status: str, reason: str) -> PromotionDecision:
        return PromotionDecision(False, status, reason, evidence)

    if not cold_start and set(candidate_schema) != set(incumbent_schema):
        added = sorted(set(candidate_schema) - set(incumbent_schema))
        removed = sorted(set(incumbent_schema) - set(candidate_schema))
        return reject(
            "rejected_schema_mismatch",
            f"feature schema differs from the incumbent; added {added}, removed {removed}. "
            "Scores across different feature sets are not comparable.",
        )

    if paired.n < MIN_HOLDOUT_ROWS:
        return reject(
            "rejected_insufficient_holdout",
            f"holdout has {paired.n} rows, below the minimum of {MIN_HOLDOUT_ROWS}; "
            "the score is not yet meaningful.",
        )

    if paired.candidate_accuracy <= MIN_ABSOLUTE_ACCURACY:
        return reject(
            "rejected_below_floor",
            f"candidate accuracy {paired.candidate_accuracy:.4f} is at or below the "
            f"absolute floor of {MIN_ABSOLUTE_ACCURACY}; a coin flip loses money on fees "
            "however weak the incumbent is.",
        )

    if (
        not cold_start
        and candidate_window_bars is not None
        and incumbent_window_bars is not None
        and candidate_window_bars < incumbent_window_bars
    ):
        return reject(
            "rejected_shorter_window",
            f"candidate trained on {candidate_window_bars} bars against the incumbent's "
            f"{incumbent_window_bars}; a partial backfill must not win by accident.",
        )

    if not cold_start and paired.diff <= threshold:
        return reject(
            "rejected_no_margin",
            f"candidate {paired.candidate_accuracy:.4f} vs incumbent "
            f"{paired.incumbent_accuracy:.4f}: the difference of {paired.diff:.4f} does not "
            f"clear the threshold of {threshold:.4f} "
            f"(max of the {MIN_MARGIN_ABS} floor and the {paired.se_diff:.4f} standard error).",
        )

    if cold_start:
        reason = (
            f"cold start: no incumbent, candidate accuracy {paired.candidate_accuracy:.4f} "
            f"clears the {MIN_ABSOLUTE_ACCURACY} floor on {paired.n} held-out rows."
        )
    else:
        reason = (
            f"candidate {paired.candidate_accuracy:.4f} beats incumbent "
            f"{paired.incumbent_accuracy:.4f} by {paired.diff:.4f} on {paired.n} shared "
            f"held-out rows, clearing the {threshold:.4f} threshold."
        )
    return PromotionDecision(True, "promoted", reason, evidence)
