# R5 — Scheduled retraining with walk-forward validation

> **PRD requirement.** Scheduled retraining (weekly) with walk-forward validation; a new model version is promoted only if it beats the incumbent on held-out data.

Status: designed, not yet implemented. Produced by a design council of three
independent designs judged against each other; this document records the chosen
approach, why, and what was taken from the runners-up.

## Chosen approach

Design 3 — "Host-cron one-shot trainer container (reject Celery), shipped as six independently valuable slices" — adopted as the base, with the promotion gate replaced by Design 2's same-holdout paired comparison and the slice order corrected.

## Rationale

All three reject Celery for the same correct reasons, so the scheduler is not the discriminator. What separates them is scope discipline, factual grounding, and whether the plan's own risk analysis matches its ordering.

Design 3 wins on grounding. Its central insight is checkable and checks out: the live model is directional_accuracy 0.5238 on n_test 9328 (models/registry/registry.json), so one standard error is 0.0052, and the current gate `candidate_score <= incumbent_score -> reject` (app/models/registry.py:77) will promote on pure noise most weeks once automated. It is also the only design that spots an existing manual toil to delete (the `tar -C models -czf - registry | ssh ...` sync at docs/RUNBOOK.md:16-17 becomes unnecessary once the trainer writes the registry on the VPS) and the only one that flags the bind-mount permission trap: the image runs as non-root `app` (Dockerfile:32-35) against a host `./models` directory the api has only ever read from.

Design 1 has the weakest foundation despite the best prose. `docker compose run` accepts no `--memory` flag, so its stated OOM mitigation does not exist — which is exactly why a profile-gated `trainer` service carrying `deploy.resources.limits` (Designs 2 and 3) is the right shape. Its rejection of a database table rests on "this repo has no alembic", but `prediction_log` was added on the shared `kline_store.metadata` and created by `create_tables()` with the import-order caveat documented at app/api/v1/endpoints/models.py:34-41; a new table is a known, cheap pattern here. Worse, its file-based `last_run.json` sits on the one volume the nightly `pg_dump` does not cover, and keeps only the most recent run — no history, contradicting R13's "retained indefinitely". Its restart-the-api promotion path is also crude: tests/test_orphaned_jobs.py exists, which suggests killing the process mid-flight has already cost this project something.

Design 2 is the most rigorous and contributed the single most important correction, but it is the heaviest: eight slices, two new tables including a hand-rolled DB lock a 20-line lockfile does better, and an S7 live post-promotion verification that is R6 scope, not R5.

The graft that matters most is Design 2's insight that the gate does not currently exist in any meaningful sense. Design 3 keeps comparing walk-forward aggregates computed over different windows, which drifts as the dataset grows and is contaminated by regime rather than model quality. R5 says "beats the incumbent on held-out data" — that requires scoring both models on the same rows. Taking Design 2's frozen-holdout head-to-head and computing Design 3's noise margin as a paired McNemar standard error over the discordant counts gives a gate that is both more correct and more powerful than either design alone.

The ordering is corrected. Design 3 ships the cron in slice 2 while its own risks section says slice 4 (predictor reload) and slice 5 (noise margin) are mandatory — i.e. it schedules a job that can promote on noise and has no effect on production. Correctness first, then propagation, then visibility, then the schedule. The scheduler is one crontab line and lands fifth, because everything before it is already valuable on its own.

## Grafted from the runners-up

- From Design 2: the promotion gate becomes a frozen-holdout head-to-head. Both incumbent and candidate are scored on the identical holdout rows through the identical feature code, replacing Design 3's comparison of walk-forward aggregates measured over different windows. This is what R5's 'beats the incumbent on held-out data' literally requires.
- From Design 2: no refit between measurement and promotion. scripts/train_ensemble.py:78 currently fits the final artifact on all data and promotes it under the walk-forward metric, so the promoted model's out-of-sample accuracy is never measured. The promoted bundle's sha256 must equal the hash of the bundle that was scored.
- From Design 2: the run row is INSERTed with status='running' BEFORE any fitting begins, so an OOM kill leaves a detectable stuck row instead of silence. Design 3 only recorded terminal outcomes.
- From Design 2: paired disagreement counts (candidate-only-correct / incumbent-only-correct / both / neither) stored as evidence, so any promotion can be audited for luck after the fact. These same counts supply the McNemar standard error that makes Design 3's noise margin a paired test rather than two independent ones.
- From Design 2: a `rejected` list plus `promotion_evidence` on the version record in registry.json, so 'why is this version active' is answerable from the registry alone, and losers stop vanishing.
- From Design 1 and 2: fail closed on feature-schema drift. If the incumbent's recorded feature_schema differs from the candidate's FEATURE_COLUMNS there is no valid head-to-head, so the run rejects and names the added/removed columns rather than auto-promoting an unmeasurable candidate.
- From Design 1: MIN_ABSOLUTE_ACCURACY floor of 0.50 — two bad models do not make a promotion, even when the candidate is the less bad one.
- From Design 1: a CI test asserting the documented cron line is real. Design 3's version is better (assert the RUNBOOK line names a compose service that actually exists, so a rename breaks CI rather than the schedule), so take the test but keep the RUNBOOK as the single source rather than adding a separate deploy/crontab.aif.
- From Design 1 and 3: a test that every terminal status the ledger can emit has an operator meaning written into RUNBOOK §8. A new status with no runbook entry fails CI.
- Rejected from Design 2: the training_run_lock table. Design 3's O_EXCL lockfile with a stale-lock escape hatch guards manual runs as well as cron, needs no schema, and is testable in-process.
- Rejected from Design 2: S7 live post-promotion verification against prediction_log. It is a genuinely good idea and it is R6 scope, not R5. File it separately.
- Rejected from Design 1: propagating promotions by restarting the api container. The version-aware predictor cache (Designs 2 and 3) achieves the same with no downtime and no risk to in-flight forecast jobs.
- New, not in any design: the pooled dataset stacks 4 pairs sharing the same timestamps, so n_holdout overstates independence by roughly 4x and the McNemar standard error is optimistic. Deliberately NOT inflating the margin now — that would be tuning without evidence. Record n_pairs in the evidence, state the caveat in RUNBOOK §8, and revisit once the ledger has a few months of real margins.

## Acceptance criteria for the requirement as a whole

- [ ] R5 is complete when a new model version is promoted if and only if it beats the incumbent measured on the SAME held-out rows by more than max(0.005, the McNemar standard error of the paired difference), with identical feature schemas, at least 500 holdout rows, candidate accuracy above 0.50, and a training window at least as long as the incumbent's. Every failing condition leaves registry.json `active` byte-identical and records which condition failed and by how much.
- [ ] The incumbent's side of every comparison is RECOMPUTED on the current holdout. A stored registry metric from an earlier run is never used as the incumbent's score.
- [ ] The promoted artifact bundle is byte-identical (sha256-verified) to the bundle that was scored. There is no refit-on-all-data between measurement and promotion — this is the behaviour change from scripts/train_ensemble.py:78.
- [ ] Every invocation writes exactly one retrain_runs row, INSERTed with status='running' before any model fitting, with a non-empty human-readable reason on every terminal status. A SIGKILL or OOM leaves a detectable 'running' row rather than silence.
- [ ] Within 60 seconds of a promotion, GET /api/v1/signal/BTCUSDT reports the new model_version with no container restart and no deploy, and every prediction_log row written after that instant carries it. Rows before it carry the old version, so the switch time is recoverable from the database alone.
- [ ] With the newest kline older than 2.5 intervals (the existing rule at app/services/market_data_status.py:26), the run exits before any training with status skipped_stale_data and exit code 0. Production is in this state today and will stay in it until the Binance 451 geo-block is resolved.
- [ ] Exit code is 0 for promoted, every rejected_*, and every skipped_*; 1 only for failed. A rejection is the gate working and must never page.
- [ ] GET /api/v1/health/detailed includes a `retraining` component that degrades the top-level status for exactly {stale, failing, stuck} — a dead cron, a failed run, and an OOM-killed run respectively — and leaves it healthy for a rejection, a fresh install, or an absent configuration.
- [ ] For any promotion in history, GET /api/v1/models/retrain-status alone answers: which two versions, which holdout window, both accuracies, the four paired counts, the margin and the threshold applied, the walk-forward estimate, the git_sha that trained it, and the artifact hash. No SSH and no log grepping.
- [ ] Two concurrent invocations: exactly one trains; the other exits 0 with status skipped_locked naming the holder. A lock older than 6h is stolen and the theft is recorded.
- [ ] registry.json is written atomically, and a corrupt or unreadable registry never silently downgrades a running API to the baseline EMA momentum model.
- [ ] scripts/retrain.py --rollback restores the previous active version, the served version follows on the next request, and the reversal is recorded in the ledger as a first-class run.
- [ ] `docker compose -f docker-compose.prod.yml ps` shows the identical container set before and after. No Celery, beat, worker, Flower, APScheduler or always-on scheduler process exists anywhere. One new profile-gated service and one crontab line.
- [ ] All tests run in the three existing CI jobs (.github/workflows/ci.yml) against SQLite — no new CI job, no Postgres service in CI, no network in tests. scripts/ci_gate.py still blocks deploy of any non-green commit.
- [ ] HONEST FRAMING, to be stated to the stakeholder rather than buried: klines are frozen at 2026-07-31 (Binance 451 to this host), so every scheduled run will correctly report skipped_no_new_data until hosting is fixed. G0 is NO-GO at -78.76% return and -4.75 Sharpe (docs/gates/G0-report.md). R5 buys process integrity — provable promotion discipline and a reconstructible history — not performance, and does not unblock live capital.
- [ ] OPEN DECISION, deliberately deferred and to be revisited with data from the ledger: the gate is directional accuracy, not Sharpe or drawdown. A model can call direction better and still lose more by trading more. Holdout Sharpe is recorded in the evidence but not gated on, because a full backtest per run costs minutes and per-fold threshold tuning, and turning that on now would fold the unfinished G0 model-iteration work into a scheduling slice. Separately, the pooled dataset stacks 4 pairs sharing timestamps, so n_holdout overstates independence by roughly 4x and the standard error is optimistic; the absolute 0.005 floor partially covers it, and the margin should not be inflated without evidence from real runs.

## Delivery slices

Each slice is independently shippable and independently valuable, and becomes
its own GitHub issue and its own release.

### 1. S1 — A promotion gate that is actually a comparison (plus stop the registry corrupting itself)

Two problems, both live today.

(1) `ModelRegistry._save()` (/Users/isupercoder/Code/github/ai-forecasting/app/models/registry.py:33-34) is a bare `write_text` — truncate-then-write. The API reads that same file at /Users/isupercoder/Code/github/ai-forecasting/app/models/ensemble_predictor.py:44-53, and `get_predictor()` swallows any failure into `None` (app/services/signal_service.py:217-229), silently downgrading the whole system to the baseline EMA momentum model. Fix: write a temp file in the same directory, then `os.replace`, the same discipline scripts/prod_backup.py:131-146 already uses for backups.

(2) `promote()` (registry.py:69-84) compares the candidate's stored `directional_accuracy` against the incumbent's stored one. Those two numbers came from different walk-forward runs over different data windows months apart; in crypto that difference is dominated by regime, not model quality. It is not a comparison. Worse, the gate is strictly-greater: with the live model at 0.5238 on n_test 9328 (models/registry/registry.json), one standard error is 0.0052, so a candidate at 0.5241 wins on nothing. Automating that produces a weekly random walk of meaningless version changes that also fragments prediction_log's per-version accuracy into useless sample sizes.

New module /Users/isupercoder/Code/github/ai-forecasting/app/models/promotion.py holds the whole R5 guarantee as pure functions over arrays — no filesystem, no database, no registry:
- `paired_scores(y_true, prob_incumbent, prob_candidate) -> PairedResult` with n, both_correct, candidate_only, incumbent_only, neither, candidate_accuracy, incumbent_accuracy, diff, se_diff. `se_diff = sqrt(candidate_only + incumbent_only) / n` — the McNemar standard error of the paired accuracy difference.
- `decide(paired, candidate_schema, incumbent_schema, candidate_window_bars, incumbent_window_bars) -> PromotionDecision(promote, status, reason, evidence)`.

Promote iff ALL of: feature schemas identical; `paired.n >= MIN_HOLDOUT_ROWS` (500); `candidate_accuracy > MIN_ABSOLUTE_ACCURACY` (0.50); candidate training window at least as long as the incumbent's; and `diff > max(MIN_MARGIN_ABS, se_diff)` with MIN_MARGIN_ABS = 0.005. Statuses: `promoted`, `rejected_no_margin`, `rejected_insufficient_holdout`, `rejected_below_floor`, `rejected_schema_mismatch`, `rejected_shorter_window`.

Known limitation to record in the docstring, not to fix now: the pooled dataset stacks 4 pairs sharing timestamps, so n overstates independence by roughly 4x and se_diff is optimistic. The absolute floor partially covers it. Do not inflate the margin without evidence — the ledger from S2 will supply it.

Registry changes: `promote(version_id, decision=None)` — when a decision is passed it is authoritative (`promote=False` raises `PromotionRejected(decision.reason)`) and `promotion_evidence` is stored on the version record; `decision=None` preserves today's stored-metric path so the 10 existing tests in tests/test_model_registry.py and hand-run local training keep working unchanged. New `record_rejection(version_id, decision)` appends to a `rejected` list so losers stop vanishing. New `prune(keep=N)` that never removes the active version or anything reachable through history.

No scheduler, no new dependency, no I/O beyond the registry file. Value on its own: the next hand-run training on prod has a defensible promotion decision instead of two unrelated numbers.

**Acceptance criteria**

- [ ] registry.json is never left truncated or partially written: an interrupted save leaves the previous index fully parseable.
- [ ] decide() returns promote=True if and only if all five conditions hold: identical feature schemas, n_holdout >= 500, candidate_accuracy > 0.50, candidate training window >= incumbent's, and diff > max(0.005, sqrt(candidate_only + incumbent_only)/n).
- [ ] Every PromotionDecision carries complete evidence: both accuracies, all four paired counts, n, se_diff, the threshold applied, both feature schemas, both window lengths, and a human-readable reason. No terminal decision has an empty reason.
- [ ] A rejected candidate is recorded under registry.json's `rejected` list with its evidence rather than disappearing.
- [ ] promote(version_id) with no decision behaves exactly as today — the 10 existing tests in tests/test_model_registry.py pass unchanged, with no edits to that file's existing cases.
- [ ] prune(keep=N) never removes the active version or any version reachable through the rollback history, and load_active still works afterwards.
- [ ] No new entry in requirements.txt, no new service, no new table.

**Tests to write first**

- tests/test_model_registry.py::test_save_is_atomic_under_a_failed_replace — monkeypatch os.replace to raise; the original registry.json is still present and parses to the pre-write content
- tests/test_model_registry.py::test_concurrent_read_never_sees_a_partial_index — a reader loads registry.json while a save is in flight; every read parses
- tests/test_promotion.py::test_paired_scores_counts_discordant_pairs — known y/prob arrays produce exact both_correct / candidate_only / incumbent_only / neither counts
- tests/test_promotion.py::test_se_diff_is_the_mcnemar_standard_error — for known (candidate_only=40, incumbent_only=30, n=1000), se_diff == sqrt(70)/1000
- tests/test_promotion.py::test_margin_below_max_of_floor_and_se_rejects — candidate 0.5241 vs incumbent 0.5238 (the live numbers); rejected, reason names both scores, the diff and the threshold it missed
- tests/test_promotion.py::test_margin_above_both_thresholds_promotes
- tests/test_promotion.py::test_exact_tie_rejects — preserves the conservative behaviour at app/models/registry.py:77
- tests/test_promotion.py::test_holdout_below_min_rows_rejects_regardless_of_margin — status rejected_insufficient_holdout, reason names the row count
- tests/test_promotion.py::test_candidate_below_absolute_floor_rejects_even_when_incumbent_is_worse — 0.49 vs 0.47 does not promote
- tests/test_promotion.py::test_feature_schema_mismatch_rejects_and_names_the_columns — incumbent ['a','b'] vs candidate ['a','b','c'] gives rejected_schema_mismatch listing 'c'
- tests/test_promotion.py::test_shorter_training_window_rejects — guards against a partial backfill winning by accident
- tests/test_promotion.py::test_no_incumbent_promotes_when_floors_pass — cold start; evidence records incumbent_accuracy as None, not 0.0
- tests/test_promotion.py::test_evidence_is_self_contained — the decision carries both accuracies, all four paired counts, n, se_diff, the applied threshold, both schemas and both window lengths, so the audit record needs no other source
- tests/test_model_registry.py::test_promote_with_decision_persists_evidence — registry.json alone answers 'why is this version active'
- tests/test_model_registry.py::test_promote_with_rejecting_decision_raises_and_leaves_active_unchanged
- tests/test_model_registry.py::test_record_rejection_keeps_the_loser_on_the_record — the rejected version appears under 'rejected' with its evidence
- tests/test_model_registry.py::test_decision_overrides_the_stored_metric_in_both_directions — a worse stored metric with a winning decision promotes; a better stored metric with a losing decision does not
- tests/test_model_registry.py::test_prune_keeps_active_and_history — prune(keep=2) with active=v5, history=[v1,v3] keeps v1, v3, v5 and removes v2, v4
- tests/test_model_registry.py::test_prune_leaves_load_active_working — after prune, ensemble_predictor.load_active still returns a working predictor
- tests/test_model_registry.py — all 10 existing tests pass unchanged under the decision=None path

### 2. S2 — scripts/retrain.py: one correct, auditable, unattended-safe retrain (no scheduler yet)

A single command an operator can run on prod today that cannot corrupt the registry, cannot silently do nothing, and cannot cry wolf.

First, extract the body of `main()` in /Users/isupercoder/Code/github/ai-forecasting/scripts/train_ensemble.py:50-107 into a reusable `train_and_register(...)` that both the existing CLI and the new entrypoint call. This also fixes a live crash path: when every symbol is skipped for insufficient candles, `pd.concat(frames_X)` at scripts/train_ensemble.py:64 raises a bare 'No objects to concatenate' traceback with nothing recorded anywhere.

New /Users/isupercoder/Code/github/ai-forecasting/app/services/retrain_runs.py defines the `retrain_runs` table on `app.services.kline_store.metadata` — the same mechanism `prediction_log` uses (app/services/model_health.py:31-45), including the import-order caveat documented at app/api/v1/endpoints/models.py:34-41: the module must be imported before `create_tables()` runs or a fresh database never gets the table. Postgres in prod, SQLite in tests (tests/conftest.py repoints DATABASE_URL before any app import). Functions: `start_run()`, `finish_run()`, `recent_runs()`, `last_successful_run()`.

New /Users/isupercoder/Code/github/ai-forecasting/scripts/retrain.py, in order:
1. Acquire an O_CREAT|O_EXCL lockfile at `models/registry/.retrain.lock` holding the pid and start time. A lock older than LOCK_TTL (6h) is stolen and the theft is recorded. Released on every exit path including exceptions.
2. INSERT the run row with status='running' BEFORE any model fitting. An OOM kill then leaves a detectable stuck row instead of silence.
3. Market-data freshness preflight via app/services/market_data_status.market_data_status against MAX(open_time_ms). Stale -> skipped_stale_data, no fitting.
4. No-new-data check: newest open_time_ms compared against the last successful run's data_end_ms. Unchanged -> skipped_no_new_data naming the frozen date. (Production is in exactly this state: Binance returns 451 to this host and klines are frozen at 2026-07-31.)
5. Build the pooled dataset across UNIVERSE, then carve a chronological holdout off the tail: `--holdout-days 45` (at 4h bars across 4 pairs, roughly 1080 rows). The holdout rolls forward every week, so no window is permanently withheld.
6. Walk-forward validation via the existing `train_walk_forward` on the TRAIN split only. Recorded as the generalisation estimate, explicitly NOT gating.
7. Fit the candidate on the train split only. Load the incumbent via `ensemble_predictor.load_active` and score BOTH on the identical holdout rows through the identical feature code path.
8. `promotion.decide(...)`, then write artifacts, record their sha256, `register()`, and either `promote(version_id, decision)` or `record_rejection(version_id, decision)`. There is NO refit-on-all-data after measurement — the promoted bundle is byte-identical to the bundle that was scored. This is the behaviour change from scripts/train_ensemble.py:78.
9. `finish_run()` with the terminal status, reason and full evidence, and print one greppable timestamped line to stdout.

Exit codes: 0 for `promoted`, every `rejected_*`, `skipped_no_new_data`, `skipped_stale_data`, `skipped_locked`. 1 only for `failed`. A rejection is the gate working correctly and must never page, or the operator learns to ignore the alert; a stale-data skip is already alerted by the `market_data` component at app/api/v1/endpoints/health.py:169-196 — one fault, one alert.

Still triggered by hand. The cron line lands in S5.

**Acceptance criteria**

- [ ] Every invocation produces exactly one retrain_runs row, INSERTed before any model fitting begins, with a non-empty reason on every terminal status. SIGKILL mid-fit leaves status='running' with finished_at_ms NULL.
- [ ] The incumbent's score in every comparison is RECOMPUTED on the current holdout. A stored registry metric is never used as the incumbent's side of the gate.
- [ ] The sha256 recorded in the run row is the hash of the artifact bundle that was scored AND the bundle written to the registry. There is no refit between measurement and promotion.
- [ ] With the newest kline older than 2.5 intervals (app/services/market_data_status.STALE_AFTER_INTERVALS), no model is fitted, status is skipped_stale_data and the exit code is 0.
- [ ] Two concurrent invocations: exactly one trains; the other exits 0 with status skipped_locked naming the holder. A lock older than 6h is stolen and the theft appears in the reason.
- [ ] Exit code is 0 for promoted, every rejected_*, and every skipped_*; 1 only for failed.
- [ ] scripts/train_ensemble.py still works as the manual/experimental entry point and shares one code path with retrain.py.
- [ ] VERIFIED ON PROD BEFORE CLOSING: `docker compose -f docker-compose.prod.yml run --rm --no-deps api python scripts/retrain.py --interval 4h` completes and writes to /app/models/registry. The image runs as non-root `app` (Dockerfile:32-35) while the host /opt/ai-forecasting/models may be root-owned; an EACCES here must be found now, not as a silent weekly failure later. Peak RSS and wall clock are recorded in the run row and pasted into this issue.
- [ ] All tests run in the existing backend CI job against SQLite. No new CI job, no Postgres service in CI, no network access in tests.

**Tests to write first**

- tests/test_retrain_runs.py::test_start_run_inserts_row_with_status_running_before_any_training — started_at_ms set, finished_at_ms NULL
- tests/test_retrain_runs.py::test_finish_run_rejects_an_empty_reason — a terminal status with a blank reason raises; the ledger must never hold an unexplained outcome
- tests/test_retrain_runs.py::test_run_id_is_unique — a duplicate raises rather than silently overwriting an earlier run's evidence
- tests/test_retrain_runs.py::test_recent_runs_orders_newest_first_and_respects_limit
- tests/test_retrain_runs.py::test_abandoned_run_stays_running_with_null_finished_at — the signal S4 reads as 'stuck'
- tests/test_retrain_runs.py::test_evidence_json_roundtrips_the_nested_payload — per-fold lists, calibration buckets and paired counts survive the TEXT column
- tests/test_retrain_runs.py::test_table_is_created_by_shared_metadata — importing the module registers retrain_runs on kline_store.metadata so create_tables() builds it
- tests/test_retrain.py::test_stale_klines_skip_before_any_fitting — newest 4h kline 3 intervals old; the fit spy is never called, status skipped_stale_data, exit 0
- tests/test_retrain.py::test_no_new_data_since_last_successful_run_skips — status skipped_no_new_data, reason names the frozen date, exit 0
- tests/test_retrain.py::test_no_symbols_with_enough_candles_is_a_structured_failure — reproduces today's bare pd.concat([]) ValueError at scripts/train_ensemble.py:64 as status=failed with a readable reason, registry untouched, exit 1
- tests/test_retrain.py::test_insufficient_rows_for_a_valid_holdout_is_a_structured_failure
- tests/test_retrain.py::test_holdout_is_strictly_after_the_training_cut — no timestamp in the candidate's training set is >= holdout_start_ms; leakage guard
- tests/test_retrain.py::test_incumbent_and_candidate_are_scored_on_identical_rows — same row count and same index for both
- tests/test_retrain.py::test_promoted_artifact_hash_equals_the_scored_artifact_hash — no post-measurement refit
- tests/test_retrain.py::test_candidate_that_loses_is_registered_but_not_promoted — active unchanged, run row records both accuracies and the margin
- tests/test_retrain.py::test_trainer_exception_records_failed_and_exits_one — run row carries the exception text, active version identical before and after
- tests/test_retrain.py::test_a_run_row_is_written_for_every_outcome — parametrized over all statuses including failed, the row most likely to be forgotten
- tests/test_retrain.py::test_second_concurrent_run_exits_zero_without_training — status skipped_locked naming the holder's run_id, fit spy never called
- tests/test_retrain.py::test_stale_lock_older_than_ttl_is_stolen_and_the_theft_recorded
- tests/test_retrain.py::test_lock_is_released_when_training_raises — next week is not blocked forever
- tests/test_retrain.py::test_git_sha_is_recorded — the run row names the code that produced the model
- tests/test_retrain.py::test_walk_forward_accuracy_is_recorded_but_not_gating — a run with a poor walk-forward number still promotes if it wins the holdout head-to-head, and both numbers are stored
- tests/test_retrain.py::test_exit_codes — 0 for promoted, all rejected_*, and all skipped_*; 1 only for failed

### 3. S3 — Promotions reach production: version-aware predictor cache and rollback

Without this slice S1 and S2 are theatre. `get_predictor()` (/Users/isupercoder/Code/github/ai-forecasting/app/services/signal_service.py:210-229) sets `_PREDICTOR_CACHE` once per process, so a promotion changes a file on disk that the running API never re-reads. A promoted model would not be served until someone redeployed.

Replace the write-once cache with one keyed on registry.json's `active` value plus its mtime: stat the index per call (cheap), and reload the joblib artifacts only when the active version changes, rebinding a fully-constructed predictor under a lock so in-flight requests never see a half-built object.

Fix the silent-degradation half at the same time. Today a reload failure hits a bare `except: _PREDICTOR_CACHE = None`, which drops the entire system to the baseline EMA momentum model with no signal anywhere that it happened — the exact quiet-degradation shape that let the Binance 451 outage report healthy for 32 hours (app/services/market_data_status.py:1-13). New behaviour: on reload failure, keep serving the currently loaded predictor and log loudly. Preserve today's behaviour only for a genuinely fresh deployment where nothing has ever loaded.

This also makes `prediction_log.model_version` (app/services/model_health.py:37) the timestamped, after-the-fact proof of when each version began serving, which is the second half of R5's 'model versions are recorded with every signal they produce'.

Add `scripts/retrain.py --rollback`, wrapping the existing `ModelRegistry.rollback()` (app/models/registry.py:86-92) and writing a retrain_runs row with status='rolled_back'. With the version-aware cache in place, the served version follows the rollback on the next request with no restart — reverting becomes as auditable and as immediate as promoting.

This is the only change in the whole plan that touches the live signal path, which is why it ships alone.

**Acceptance criteria**

- [ ] Within 60 seconds of a promotion writing registry.json, GET /api/v1/signal/BTCUSDT reports the new model_version with no container restart and no deploy.
- [ ] prediction_log rows written after that instant carry the new version and rows before it carry the old one, so the switch time is recoverable from the database alone.
- [ ] A corrupt, truncated or unreadable registry.json never downgrades a process that has already loaded an ensemble to the baseline momentum model; it keeps serving the loaded predictor and logs the failure.
- [ ] The active version is stat-checked, not reloaded, on the hot path: a load_active spy is called once across 20 requests when nothing changed.
- [ ] scripts/retrain.py --rollback restores the previous active version, the served version follows on the next request, and a retrain_runs row records it.
- [ ] No change to the signal response schema.

**Tests to write first**

- tests/test_predictor_reload.py::test_predictor_reloads_after_the_active_version_changes_on_disk — serve a signal (v1), promote v2 in the registry file, the next request reports v2 with no restart
- tests/test_predictor_reload.py::test_predictor_is_not_reloaded_when_active_is_unchanged — a load_active spy is called once across 20 requests; no per-request model deserialisation
- tests/test_predictor_reload.py::test_reload_failure_keeps_serving_the_previous_predictor — corrupt registry.json after a successful load; the signal still carries v1 and does NOT report 'baseline-momentum-v0'
- tests/test_predictor_reload.py::test_missing_artifact_directory_keeps_the_previous_predictor
- tests/test_predictor_reload.py::test_missing_registry_at_startup_still_falls_back_to_baseline — preserves today's behaviour for a fresh deployment
- tests/test_predictor_reload.py::test_concurrent_calls_never_see_a_half_built_predictor — threaded calls always get a predictor whose models dict matches its version_id
- tests/test_signal_contract.py::test_signal_model_version_matches_the_registry_active_version — end to end through TestClient against GET /api/v1/signal/BTCUSDT
- tests/test_model_health.py::test_prediction_log_rows_carry_the_version_that_produced_them_across_a_promotion — rows before say v1, rows after say v2, and health_summary does not blend them
- tests/test_retrain.py::test_rollback_restores_the_previous_active_version
- tests/test_retrain.py::test_rollback_writes_a_retrain_runs_row — status='rolled_back' with a required reason; reverting is as auditable as promoting
- tests/test_retrain.py::test_rollback_without_history_exits_nonzero_and_changes_nothing — matches the existing RuntimeError at app/models/registry.py:87-88
- tests/test_retrain.py::test_rollback_and_a_normal_retrain_are_mutually_exclusive — argument parsing rejects both in one invocation

### 4. S4 — Honest monitoring: retraining freshness in /health/detailed and a status endpoint

A weekly job nobody watches is a weekly job that stops working. This ships BEFORE the scheduler on purpose: it is the mechanism that makes a missing, dead or never-installed cron visible, and this project has already been burned twice by the opposite (app/services/backup_status.py:1-27, app/services/market_data_status.py:1-13).

New /Users/isupercoder/Code/github/ai-forecasting/app/services/retrain_status.py, shaped exactly like app/services/backup_status.py — including `DEGRADED_STATUSES` and `BENIGN_STATUSES` owned in this module rather than restated as literals in the consumer. That ownership rule exists because health.py used to hardcode ('stale','missing') separately, so renaming a status left backups rotting while /health/detailed reported healthy (backup_status.py:20-26).

Statuses and the judgement calls behind them:
- `healthy` — the newest terminal run is within 8 days (weekly cadence plus one day of slack, the same shape as backup_status.MAX_AGE_HOURS=26 for a nightly job).
- `stale` — no terminal run in more than 8 days. DEGRADED. This is what a dead or uninstalled cron looks like.
- `failing` — the most recent terminal run is `failed`. DEGRADED.
- `stuck` — a row with status='running' and finished_at_ms NULL older than 6h. DEGRADED. This is what an OOM kill looks like.
- `missing` — the ledger is empty. Benign: a fresh install is not a fault.
- `not_configured` — no engine. Benign: local dev.
- A `rejected_*` most-recent run counts as HEALTHY. The gate working is not a fault, and if a rejection paged, the operator would learn to ignore the panel within a month.
- `skipped_no_new_data` and `skipped_stale_data` are benign for the aggregate, because the `market_data` component (app/api/v1/endpoints/health.py:169-196) already degrades on that identical root cause. One fault, one alert. But the retraining component still reports the reason and the date data stopped arriving, so the panel does not imply retraining is producing models when it is not.

Wire a `retraining` component into GET /api/v1/health/detailed next to the backups block (health.py:151-167). Add GET /api/v1/models/retrain-status returning the last N runs plus the active version and its promotion evidence, following the None-engine handling already at app/api/v1/endpoints/models.py:51-52.

**Acceptance criteria**

- [ ] GET /api/v1/health/detailed includes a `retraining` component with status, last run time, outcome and age.
- [ ] The top-level status degrades for exactly {stale, failing, stuck} and for nothing else. A rejected most-recent run leaves it healthy.
- [ ] DEGRADED_STATUSES and BENIGN_STATUSES are defined in app/services/retrain_status.py and consumed by health.py; no status literal is restated in the endpoint.
- [ ] Every status the module can emit is in exactly one of the two sets, enforced by a test.
- [ ] GET /api/v1/models/retrain-status returns the last N runs plus the active version and its promotion evidence, and returns an empty shape with HTTP 200 (never 500) when no engine is configured.
- [ ] For any promotion in history, the endpoint alone answers: which two versions, which holdout window, both accuracies, the paired counts, the margin and threshold, the walk-forward estimate, the git_sha and the artifact hash. No SSH, no log grepping.
- [ ] The health endpoint never raises on a malformed or unreadable ledger.

**Tests to write first**

- tests/test_retrain_status.py::test_empty_ledger_reads_missing_not_healthy — a fresh install is not a fault and is not a success either
- tests/test_retrain_status.py::test_no_engine_reads_not_configured
- tests/test_retrain_status.py::test_recent_promoted_run_is_healthy
- tests/test_retrain_status.py::test_recent_rejected_run_is_healthy — the gate working is not a fault; this is the test that stops the dashboard crying wolf every week the model fails to improve
- tests/test_retrain_status.py::test_most_recent_terminal_run_failed_is_failing_and_names_the_reason
- tests/test_retrain_status.py::test_no_terminal_run_in_nine_days_is_stale — boundary tested at 7d healthy, 8d healthy, 9d stale
- tests/test_retrain_status.py::test_running_row_older_than_six_hours_is_stuck
- tests/test_retrain_status.py::test_running_row_younger_than_six_hours_is_not_stuck
- tests/test_retrain_status.py::test_skipped_no_new_data_is_benign_for_the_aggregate_but_reports_the_frozen_date
- tests/test_retrain_status.py::test_malformed_or_unreadable_ledger_reads_failing_rather_than_raising — the health endpoint must never 500 on a bad status read
- tests/test_retrain_status.py::test_degraded_and_benign_status_sets_partition_every_status_the_module_can_emit — a new status must be classified or the test fails
- tests/test_retrain_health_degradation.py::test_health_detailed_includes_a_retraining_component — mirrors the existing tests/test_backup_health_degradation.py
- tests/test_retrain_health_degradation.py::test_stale_retraining_degrades_the_top_level_status
- tests/test_retrain_health_degradation.py::test_failing_retraining_degrades_the_top_level_status
- tests/test_retrain_health_degradation.py::test_stuck_retraining_degrades_the_top_level_status
- tests/test_retrain_health_degradation.py::test_rejected_retraining_leaves_the_top_level_status_healthy
- tests/test_retrain_health_degradation.py::test_health_py_consumes_degraded_statuses_from_the_module_rather_than_restating_literals — the exact bug documented at app/services/backup_status.py:20-26
- tests/test_endpoints_models.py::test_retrain_status_endpoint_returns_the_last_runs_and_the_active_version
- tests/test_endpoints_models.py::test_retrain_status_endpoint_returns_full_evidence_for_a_promotion — both accuracies, the paired counts, the margin, the walk-forward estimate, the git_sha and the artifact hash in one response
- tests/test_endpoints_models.py::test_retrain_status_endpoint_returns_an_empty_shape_not_500_when_the_engine_is_none — matches app/api/v1/endpoints/models.py:51-52

### 5. S5 — The schedule: profile-gated trainer service, one crontab line, RUNBOOK §8

Everything before this is already correct and already valuable, which is why the scheduler lands fifth and is the smallest slice in the set.

Scheduler decision, recorded here so the divergence from the PRD is deliberate rather than silent. The PRD says Celery (docs/PRD-trading-bot.md:94-96 and the §5 architecture diagram). Reject it: Celery is a distributed task queue for many short async jobs with retries and fan-out; this is ONE job, ONCE A WEEK. It costs a worker container plus a beat container permanently resident on a 5.8GB box already running ~19 containers with limits summing to ~3.3GB (docker-compose.prod.yml:9-11), a new dependency in the API image, and new silent-failure modes (dead worker, beat schedule drift) that need Flower to see. Reject APScheduler in-process: it would fit 15+ boosted-tree models inside the API container's 1280M limit (docker-compose.prod.yml:86) and its event loop, where an OOM takes down the signal endpoint and halts trading, and any multi-worker config double-fires. Reject a compose `scheduler` service: a container idle 167 hours a week that you now have to monitor, in exchange for a schedule line. Host cron is the precedent that already works here (scripts/prod_backup.py:8-9, docs/RUNBOOK.md:33-39 — nightly 03:17, root crontab, /var/log/aif-backup.log): zero new services, zero new dependencies, memory reserved only while training, visible in `crontab -l`, and a crash is a nonzero exit in a log file. Amend docs/PRD-trading-bot.md R5 and the §5 note rather than diverging quietly.

Add a `trainer` service to docker-compose.prod.yml: `profiles: ["tools"]` so `docker compose up -d` never starts it, the same build context as api, `command: python scripts/retrain.py --interval 4h`, `./models:/app/models` (the same path api reads at docker-compose.prod.yml:70 — otherwise the job writes a registry nothing reads), DATABASE_URL, and `deploy.resources.limits: {memory: 1536M, cpus: '1.0'}`. The profile-gated service is what makes the memory cap possible: `docker compose run` has no `--memory` flag, so an ad-hoc one-shot container would be unbounded.

Host root crontab, Sunday 04:17 UTC — one hour after the existing 03:17 nightly backup, so the pre-retrain registry and database state are always inside a fresh, restore-drilled dump:

`17 4 * * 0 cd /opt/ai-forecasting && /usr/bin/docker compose -f docker-compose.prod.yml run --rm -T trainer >> /var/log/aif-retrain.log 2>&1`

The lockfile from S2 already guards a manual run colliding with cron, so no flock wrapper is needed.

RUNBOOK §8 Retraining is the canonical home for that cron line (tested against the compose file, so a service rename breaks CI instead of silently breaking the schedule), the log path, the exit-code contract, a table of every terminal status and what the operator should do about it, the rollback procedure, and the measured peak RSS and wall clock from S2. Delete step 2 of RUNBOOK §1 (`tar -C models -czf - registry | ssh ...`): the trainer now writes the registry directly on the VPS, so the manual sync is dead.

Optional: ping HEALTHCHECKS_RETRAIN_URL on terminal outcomes only, so a crashed run does not report success.

**Acceptance criteria**

- [ ] `docker compose -f docker-compose.prod.yml ps` shows the identical container set before and after this work. `trainer` appears only under `--profile tools`. No Celery, beat, worker, Flower or scheduler process exists anywhere in the stack.
- [ ] The VPS root crontab contains the RUNBOOK §8 line and /var/log/aif-retrain.log has an entry dated within the last 8 days.
- [ ] Peak trainer RSS stays inside the 1536M limit and wall time is under 30 minutes, both measured on prod, recorded in the retrain_runs row and written into RUNBOOK §8.
- [ ] RUNBOOK §8 documents the cron line, the log path, the exit-code contract, every terminal status with its operator action, and the rollback procedure.
- [ ] Step 2 of RUNBOOK §1 (the manual tar-over-ssh registry sync) is deleted, and a test prevents it returning.
- [ ] docs/PRD-trading-bot.md R5 and the §5 architecture note replace Celery/Redis with host cron, with the reasoning recorded.
- [ ] A trainer killed mid-run leaves registry.json parseable with `active` unchanged, leaves no lock that blocks beyond its 6h TTL, and the following week's run completes normally.

**Tests to write first**

- tests/test_compose_trainer_service.py::test_trainer_is_profile_gated — parsing docker-compose.prod.yml, services.trainer.profiles == ['tools'] and trainer is absent from the default `up` service set
- tests/test_compose_trainer_service.py::test_trainer_mounts_the_same_registry_path_as_api — both bind ./models:/app/models (docker-compose.prod.yml:70)
- tests/test_compose_trainer_service.py::test_trainer_has_explicit_memory_and_cpu_limits — an unbounded training container on a 5.8GB shared box is the OOM risk this guards; a future edit removing them fails CI rather than the VPS
- tests/test_compose_trainer_service.py::test_trainer_receives_database_url
- tests/test_retrain_cron.py::test_runbook_cron_line_references_a_compose_service_that_exists — a rename breaks CI instead of silently breaking the schedule
- tests/test_retrain_cron.py::test_runbook_cron_line_uses_run_rm_not_exec — `exec` would need a running container and would train inside the api's 1280M limit
- tests/test_retrain_cron.py::test_runbook_cron_line_redirects_to_a_log_file — a silent cron is an unobservable cron
- tests/test_retrain_cron.py::test_runbook_cron_hour_does_not_collide_with_the_backup_window — 03:17 in scripts/prod_backup.py:8-9
- tests/test_retrain_cron.py::test_runbook_documents_every_terminal_status_the_ledger_can_emit — statuses are enumerated from the code; a status with no runbook entry fails the test
- tests/test_retrain_cron.py::test_runbook_no_longer_documents_the_manual_registry_tar_sync — the dead procedure cannot come back by copy-paste
- tests/test_release.py::test_prd_r5_no_longer_specifies_celery — the PRD amendment is asserted, so the doc and the system cannot drift apart again

### 6. S6 — Retraining panel on the dashboard

Lowest-value slice in the set — S4 already makes the evidence reachable over HTTP — but it is what makes the weekly outcome visible to the second stakeholder, who has dashboard access and not SSH.

Put the parsing and formatting in a new /Users/isupercoder/Code/github/ai-forecasting/frontend/src/lib/retrain-status.ts with a colocated retrain-status.test.ts, following the existing convention (frontend/src/lib/system-status.ts and system-status.test.ts). frontend/src/lib/api.ts gains the fetch against /api/v1/models/retrain-status, and frontend/src/components/models.tsx renders a Retraining card: last run time and outcome, the active version with its walk-forward accuracy, the candidate and incumbent holdout accuracies side by side with the margin, and for a rejection, the margin it missed by.

The design constraint that matters is tone, and it is the same reasoning that put exit code 0 on rejections in S2. A rejection is the single most common outcome of a healthy weekly loop and must render as a normal informational state, not an error, or the operator learns to ignore the panel. `skipped_no_new_data` must render the date market data stopped arriving rather than a generic success — production has been frozen since 2026-07-31 and the panel must say so out loud.

**Acceptance criteria**

- [ ] The Models tab shows last retrain time, outcome, active version and its walk-forward accuracy, and the candidate-vs-incumbent holdout accuracies with the margin.
- [ ] A rejected outcome renders as a normal informational state with no error styling.
- [ ] A never-run state renders an explicit message; an API failure renders a degraded state; neither renders a blank card.
- [ ] skipped_no_new_data and skipped_stale_data render the reason and the date market data stopped arriving.
- [ ] Runs with null accuracies never render NaN.
- [ ] Typecheck passes and the frontend CI job stays green.

**Tests to write first**

- frontend/src/lib/retrain-status.test.ts::formats a promoted run with both accuracies and the margin
- frontend/src/lib/retrain-status.test.ts::classifies every rejected_* status as informational, not error
- frontend/src/lib/retrain-status.test.ts::parses a run with null accuracies (skipped before training) without producing NaN
- frontend/src/lib/retrain-status.test.ts::maps stale, failing and stuck to a degraded presentation
- frontend/src/components/models.test.tsx::renders the last retrain outcome, the active version and its accuracy
- frontend/src/components/models.test.tsx::renders a rejection with no error styling and shows the margin it missed by
- frontend/src/components/models.test.tsx::renders skipped_no_new_data with the date data stopped arriving, not as a generic success
- frontend/src/components/models.test.tsx::renders an explicit never-run empty state rather than a blank card
- frontend/src/components/models.test.tsx::renders a degraded state rather than a blank panel when the API call fails
