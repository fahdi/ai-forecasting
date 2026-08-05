# R1 — Retrain the boosted ensemble (XGBoost/LightGBM/CatBoost) on crypto OHLCV at 4h AND daily bars; TF/PyTorch removed

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

Daily bars are missing end to end: no 1d model is registered (models/registry/registry.json), no 1d klines are ingested (docker-compose.prod.yml:90 streams 4h only), and the serving interval is a module constant (app/services/signal_service.py:29) rather than a parameter, so there is nowhere to plug a daily model in. Related holes: (a) app/models/ensemble_predictor.py:56-64 reads only feature_columns from the manifest, so a 1d model would be served against 4h candles with no mismatch check even though the manifest records 'interval' (scripts/train_ensemble.py:82-87); (b) app/services/signal_service.py:224-225 swallows any registry load failure and silently falls back to the baseline EMA model (app/services/signal_service.py:33, MODEL_VERSION='baseline-momentum-v0'), and since models/registry/ is gitignored (.gitignore:12) and only host-mounted (docker-compose.prod.yml:70), a missing artifact in prod degrades to a hand-written momentum rule with no health signal - neither /health/detailed (app/api/v1/endpoints/health.py:38-195) nor /api/v1/models/health (app/api/v1/endpoints/models.py:48-58) reports which model version is active; (c) the promotion gate only requires beating the incumbent (app/models/registry.py:69-86), there is no absolute floor, and the shipped model's 0.5238 walk-forward accuracy is asserted by no test.

## Chosen approach

Design B (correctness-first: interval-tagged predictor with fail-closed load, honest model health, absolute promotion floor, then daily model trained from resampled 4h klines)

## Rationale

Both designs agree on the ordering (interval on the artifact -> honest health -> promotion floor -> daily model), so the decision turns on two places where they differ, and B wins both.

First, slice 4's data source. A refuses to derive 1d bars from stored 4h bars and therefore ships plumbing that registers nothing: its own behaviour text admits "the actual registered 1d artifact is not [testable], and must not be claimed as shipped". That is a slice whose entire value is deferred behind a blocker (Binance 451) we cannot clear. B derives daily bars by aggregating the 4h klines already in the table. A's objection ("silently change the label semantics") does not hold on the facts: Binance 4h bars are UTC-aligned at 00/04/08/12/16/20, so six consecutive bars aggregate to exactly the 1d bar Binance would serve (first open, max high, min low, last close, summed volume). This is aggregation, not synthesis, and it is exact provided incomplete days are dropped. B therefore ends R1 with a real registered 1d model and a real 1d signal, today, with the exchange still returning 451. That is the difference between closing the gap and describing it.

Second, the failure semantics in slice 1. A keeps the silent downgrade: a broken registry returns None and the hand-written EMA rule serves under a normal-looking response. B distinguishes "no registry at all" (documented baseline, unchanged) from "registry present but unloadable" (hard error surfaced as 503). The production bug being closed is precisely that a missing artifact on a gitignored, host-mounted volume degrades to a momentum rule with nobody the wiser; fail-closed means the request fails, not that it quietly answers with something else. B also adds the interval-mismatch guard at scoring time, which is the actual protection against a 1d model being fed 4h bars once slice 4 lands.

Grafted from A: the explicit endpoint error contract in slice 4 (unknown horizon is 400; a horizon with no registered model is a named error, never a baseline signal mislabelled '1d'), the `interval_delta` pure helper so the staleness window follows the interval instead of a module constant, per-interval activation keeping the legacy `active` key as the default-interval pointer for back-compat, and the discipline of explicitly resetting `_PREDICTOR_CACHE` in tests.

Corrected in both: they invented an OK/DEGRADED status vocabulary that does not exist in this codebase. app/services/market_data_status.py and backup_status.py both use lowercase "healthy"/"stale"/"missing"/"unknown"/"not_configured". model_status must use "healthy"/"degraded"/"error"/"missing" to match, or /health/detailed aggregation will silently mis-handle it.

Cut as manufactured: both designs propose a test pinning the shipped 0.5238 walk-forward number by reading models/registry/registry.json. That directory is gitignored and host-mounted only, so the test cannot run in CI - it would pass vacuously or fail on every clean checkout. The boundary tests around the floor already give the regression protection. Also cut A's "train_walk_forward on synthetic data clears the floor" test: accuracy on synthetic data guarantees nothing about the market and is a flake generator.

Floor value: 0.51, not A's 0.52. With n_test 9328 the standard error on directional accuracy is about 0.005, so 0.51 sits roughly two standard errors above a coin flip - it rejects a worthless model while leaving the shipped 0.5238 real headroom. A floor of 0.52 leaves 0.0038 of margin and would reject the first mildly-noisy retrain of a model that is fine.

## Grafted, and explicitly rejected

- From Design A: the pure `interval_delta(interval) -> pd.Timedelta` helper, folded into Slice 1 so the staleness window and horizon are computed from a parameter instead of the module constants at app/services/signal_service.py:29-32.
- From Design A: Slice 4's explicit endpoint error contract - unknown horizon returns 400 naming the supported intervals, and a known horizon with no registered model returns a named error rather than a silent baseline fall-through mislabelled with that horizon.
- From Design A: keeping the registry's existing `active` key as the default-interval pointer alongside the new active_by_interval map, for back-compat with existing readers.
- From Design A: the discipline of explicitly resetting the _PREDICTOR_CACHE module global in every test that touches get_predictor, rather than relying on import or test ordering.
- From Design A's risk list: the deploy note that models/registry/ is gitignored (.gitignore:12) and host-mounted (docker-compose.prod.yml:70), so Slice 1's fail-closed load must be preceded by inspecting the live manifest.json and Slice 2 must ship in the same window.
- Correction applied to both designs: the invented OK/DEGRADED status vocabulary is replaced by the lowercase 'healthy'/'degraded'/'error'/'missing' already used by app/services/market_data_status.py and app/services/backup_status.py.
- Correction applied to both designs: the promotion floor is 0.51 rather than 0.52, sized at roughly two standard errors above a coin flip for n_test 9328 so it leaves the shipped 0.5238 real headroom.
- Cut from both designs: the test pinning the shipped 0.5238 by reading the real models/registry/registry.json - that path is gitignored and host-mounted, so the test cannot run in CI and would pass vacuously on a clean checkout.
- Cut from Design A: the test asserting train_walk_forward on a synthetic dataset clears MIN_DIRECTIONAL_ACCURACY - accuracy on synthetic data guarantees nothing about the market and is a flake generator.
- Rejected from Design A: its refusal to aggregate 4h bars into 1d. Binance 4h bars are UTC-aligned at 00/04/08/12/16/20, so six consecutive complete bars aggregate to exactly the exchange's daily bar; with incomplete days dropped this is exact aggregation, not synthesis, and it is what lets Slice 4 register a real model today instead of shipping plumbing that registers nothing.

## Acceptance criteria

- [ ] Every slice's tests pass with no network access, no exchange API keys, no running freqtrade, and no rows added to the klines table beyond what is already stored - verified by running the backend test job offline.
- [ ] No new service, container, process or third-party dependency is introduced. scripts/train_ensemble.py, scripts/ci_gate.py, scripts/release.py, the host cron backup and the three existing CI jobs are reused unchanged except where a slice explicitly states otherwise.
- [ ] Every new status/classification function is pure over caller-supplied scalars with the caller owning the registry read, matching the signature shape of app/services/market_data_status.py and app/services/backup_status.py. No new module reads the filesystem inside a status function.
- [ ] All new status strings use the existing lowercase vocabulary ("healthy", "degraded", "error", "missing", "stale", "unknown"). No OK/DEGRADED constants are introduced.
- [ ] No health or status surface ever reports "healthy" while the hand-written baseline (MODEL_VERSION = 'baseline-momentum-v0') is what will actually serve.
- [ ] Each slice is written test-first: the new tests are committed failing, and each failure is demonstrably for the intended reason (assertion on the new behaviour) rather than an ImportError or a typo.
- [ ] Each slice is independently shippable and gets its own release via scripts/release.py; scripts/ci_gate.py must be green on the commit before deploy.
- [ ] Any statement about production 1d data is honest: live 1d ingestion from Binance is NOT enabled or verified by this work and must not be claimed as such while the VPS receives HTTP 451.
- [ ] models/registry/ remains gitignored. No test asserts on the contents of the real production registry; every registry test builds its own fixture under tmp_path.

## Delivery slices

### 1. Slice 1: the model artifact declares its interval, and a broken registry stops being a silent downgrade

Two coupled correctness fixes to the serving path, both prerequisites for any daily model.

(1) Interval becomes a property of the artifact. scripts/train_ensemble.py already writes `interval` into manifest.json, but app/models/ensemble_predictor.py's load_active() reads only feature_columns and drops it. EnsemblePredictor gains an `interval` attribute populated from the manifest. A manifest with no `interval` key is a load failure, not an implicit '4h' - a model of unknown periodicity is never served. EnsemblePredictor.prob_long / prob_long_series / member_votes are given the interval of the candles they are being asked to score and raise IntervalMismatchError when it disagrees with self.interval, so a 1d model can never be scored against 4h bars.

(2) A registry that exists but cannot be loaded stops being invisible. app/services/signal_service.py get_predictor() currently wraps load_active in `except Exception: _PREDICTOR_CACHE = None`, which turns a missing joblib file, a corrupt registry.json or a manifest without an interval into a normal-looking baseline-momentum response. Split the two cases: MODEL_REGISTRY_PATH pointing at a directory with no registry.json still returns None and the documented EMA baseline (that is the intended dev/first-boot path), but a registry.json that is present and fails to load propagates. The signal endpoint maps that to HTTP 503 with a body naming the failure. The failure is logged with structlog including the exception, not swallowed.

Also lands the small pure helper the later slices need: `interval_delta(interval: str) -> pd.Timedelta` mapping '4h' and '1d', raising ValueError on anything else. STALE_AFTER stops being a module constant computed from INTERVAL and becomes 2 * interval_delta(interval) computed per call; _is_stale takes the delta as an argument. INTERVAL remains only as the baseline fallback's interval.

No behaviour change for the healthy 4h path. Fully testable offline with fixture registries on tmp_path.

DEPLOY NOTE for the issue body: this is a behaviour change on the production host. models/registry/ is gitignored (.gitignore:12) and host-mounted (docker-compose.prod.yml:70), so if the live manifest.json lacks an `interval` key the endpoint will start returning 503 where it previously served the momentum rule. Inspect the prod manifest before deploying, and ship Slice 2 in the same window so an operator can see why.

**Acceptance**

- [ ] EnsemblePredictor.interval exists and is sourced from manifest.json; it is never defaulted, inferred or hardcoded anywhere in app/.
- [ ] load_active() raises a named exception (not returns None) for a manifest missing `interval`, so the failure is distinguishable from 'no model registered'.
- [ ] Scoring a predictor against candles of a different interval raises IntervalMismatchError before any prediction is produced.
- [ ] get_predictor() distinguishes absent-registry (returns None, baseline serves) from present-but-broken (propagates). The bare `except Exception: None` at app/services/signal_service.py:224-225 is gone.
- [ ] The signal endpoint returns 503 with a reason on a load failure and never returns a 200 whose model_version is the baseline while a registry is present and broken.
- [ ] interval_delta is a pure function raising ValueError on unknown intervals; STALE_AFTER is no longer a module-level constant and _is_stale takes the delta as a parameter.
- [ ] The existing 4h signal tests pass unchanged - no regression to the healthy path.
- [ ] All new tests run offline against tmp_path fixtures; none touch models/registry/ or the network.
- [ ] Every test that exercises get_predictor resets _PREDICTOR_CACHE explicitly rather than relying on import or test ordering.

**Tests first**

- tests/test_ensemble_predictor.py::test_load_active_exposes_manifest_interval - fixture registry on tmp_path whose manifest records interval='4h'; load_active(...).interval == '4h'
- tests/test_ensemble_predictor.py::test_load_active_exposes_1d_interval - same with interval='1d' yields predictor.interval == '1d'
- tests/test_ensemble_predictor.py::test_load_active_rejects_manifest_without_interval - manifest missing the key raises (named error), and specifically does NOT return a predictor defaulting to '4h'; assert the raise, not merely falsiness
- tests/test_ensemble_predictor.py::test_scoring_rejects_interval_mismatch - a predictor with interval='1d' asked to score candles declared '4h' raises IntervalMismatchError and returns no probability
- tests/test_signal_service.py::test_interval_delta_maps_known_intervals - interval_delta('4h') == pd.Timedelta(hours=4), interval_delta('1d') == pd.Timedelta(days=1)
- tests/test_signal_service.py::test_interval_delta_rejects_unknown_interval - interval_delta('7m') raises ValueError naming the value
- tests/test_signal_service.py::test_get_predictor_returns_none_when_registry_absent - MODEL_REGISTRY_PATH points at a nonexistent dir; get_predictor() returns None and the baseline path is unchanged
- tests/test_signal_service.py::test_get_predictor_raises_when_registry_present_but_unloadable - registry.json names an active version whose artifact dir has no joblib files; get_predictor() propagates instead of returning None
- tests/test_signal_endpoint.py::test_signal_returns_503_when_model_load_fails - endpoint over an unloadable registry returns 503 whose body names the failure, and does NOT return a 200 carrying model_version 'baseline-momentum-v0'

### 2. Slice 2: /health surfaces answer which model is actually serving, at which interval

Today neither /health/detailed (app/api/v1/endpoints/health.py:38-195) nor /api/v1/models/health (app/api/v1/endpoints/models.py:48-58) reports which model version is active, so the silent baseline downgrade closed in Slice 1 was undetectable after the fact and a future one would be too.

New app/services/model_status.py with a single pure function over caller-supplied scalars, matching the shape of app/services/market_data_status.py and app/services/backup_status.py - the caller owns reading models/registry/registry.json, the function only classifies:

    model_status(active_version: str | None, interval: str | None, directional_accuracy: float | None, load_error: str | None, floor: float) -> dict

Status vocabulary matches the existing modules exactly (lowercase): 'healthy' only when a trained ensemble is active, loadable and at or above the floor; 'error' when load_error is set (Slice 1's failure), carrying the failure text in the reason; 'missing' when there is no registry/active version at all, with the reason naming the baseline-momentum-v0 fallback that will serve; 'degraded' when a model is active but its recorded directional_accuracy is below the floor. The returned dict always carries version_id, interval and directional_accuracy (None where unknown) so the answer to 'what was serving on date X' is a single GET.

Wired into both endpoints. The models block of /health/detailed contributes to overall status so the aggregate is never 'healthy' while the baseline is what serves.

The `floor` parameter is a caller-supplied argument in this slice with the value passed in from the endpoint; Slice 3 makes it a module constant on the registry and the endpoints import it from there. Fully testable offline.

**Acceptance**

- [ ] app/services/model_status.py contains one pure function over scalars; it imports nothing that touches the filesystem, the database or the network, and the caller performs the registry read.
- [ ] Status strings are drawn only from the existing lowercase vocabulary; 'healthy' is returned only when a trained ensemble is active, loadable and at or above the floor.
- [ ] Both /api/v1/models/health and the models block of /health/detailed report active version_id, interval and directional_accuracy.
- [ ] The overall /health/detailed status is not 'healthy' when the models block is 'missing', 'degraded' or 'error'.
- [ ] Every non-healthy result carries a human-readable reason that names the specific cause, and the missing case explicitly names the baseline momentum fallback.
- [ ] The Slice 1 load failure is observable end to end: an unloadable registry produces status 'error' on the health endpoint, not a silent gap.
- [ ] All tests in tests/test_model_status.py pass without any fixture, tmp_path or monkeypatch, proving purity.

**Tests first**

- tests/test_model_status.py::test_healthy_when_trained_model_active_above_floor - returns status 'healthy' and echoes version_id, interval and directional_accuracy
- tests/test_model_status.py::test_missing_when_no_active_version - active_version None -> status 'missing', reason names baseline-momentum-v0 as what will serve; assert status != 'healthy' explicitly
- tests/test_model_status.py::test_error_when_load_failed - load_error set -> status 'error' carrying the failure text; never 'healthy' even when active_version is present
- tests/test_model_status.py::test_degraded_when_below_floor - active model with accuracy under the floor -> 'degraded', with a reason distinct from the missing-model case and naming both the floor and the observed value
- tests/test_model_status.py::test_status_is_pure - two identical calls return equal dicts, and the module performs no filesystem or network access (no tmp_path fixture required by any test in this file)
- tests/test_model_status.py::test_status_vocabulary_matches_existing_modules - the returned status is one of the lowercase set used by market_data_status/backup_status
- tests/test_health_endpoint.py::test_models_health_reports_active_version_and_interval - GET /api/v1/models/health over a tmp registry holding a trained model exposes that version_id and its interval
- tests/test_health_endpoint.py::test_detailed_health_not_healthy_when_no_trained_model - /health/detailed with MODEL_REGISTRY_PATH at an empty tmp dir reports the models block 'missing' and the overall status is not 'healthy'

### 3. Slice 3: absolute accuracy floor in the promotion gate

app/models/registry.py promote() only compares a candidate against the incumbent (lines 97-130). With an empty registry - which is exactly the situation for a new interval, and therefore for the 1d model in Slice 4 - `incumbent_id is None` and the candidate self-promotes at any accuracy at all, including a coin flip.

Add a module-level MIN_DIRECTIONAL_ACCURACY = 0.51 that every candidate must clear regardless of incumbent, applied on both the legacy stored-metric path and alongside a `decision` from app.models.promotion. A candidate below the floor raises PromotionRejected with a message naming both the floor and the observed value, and is written to the registry's 'rejected' list via the existing record_rejection() plumbing so a rejected retrain leaves a trace. The floor and the beat-the-incumbent rule are independent: a candidate that beats a weak incumbent but sits below the floor is still rejected. A rejected promotion leaves the previous active version and history untouched, consistent with the existing atomic _save() discipline.

Why 0.51: with the shipped model's n_test of 9328 the standard error on directional accuracy is roughly 0.005, so 0.51 is about two standard errors above a coin flip - it rejects a worthless model while leaving the shipped 0.5238 genuine headroom. A tighter floor would reject the first mildly noisy retrain of a model that is fine.

Slice 2's endpoints stop passing a literal and import MIN_DIRECTIONAL_ACCURACY from the registry module, so the health surface and the gate cannot disagree about what 'good enough' means.

Explicitly NOT in scope: any test that reads the real models/registry/registry.json to pin the shipped 0.5238. That directory is gitignored and host-mounted, so such a test cannot run in CI and would pass vacuously on a clean checkout. The boundary tests below provide the regression protection instead. Pure registry work on tmp_path; no training, no exchange.

**Acceptance**

- [ ] MIN_DIRECTIONAL_ACCURACY is a single module-level constant in app/models/registry.py set to 0.51, imported wherever else the floor is needed - no duplicated literals anywhere in app/ or scripts/.
- [ ] promote() rejects any candidate below the floor on every path (empty registry, incumbent present, and with an explicit promotion decision).
- [ ] The floor check and the beat-the-incumbent check are independent; failing either rejects.
- [ ] The boundary is inclusive: a candidate exactly at the floor promotes.
- [ ] Every floor rejection raises PromotionRejected with a message containing both the floor and the observed value, and is recorded in the registry's 'rejected' list.
- [ ] A rejected promotion mutates nothing: active, history and versions are unchanged and the index file is intact.
- [ ] No test reads models/registry/ or any path outside tmp_path.
- [ ] No test asserts a model-accuracy threshold against synthetically generated training data.

**Tests first**

- tests/test_model_registry.py::test_promote_rejects_first_model_below_floor - empty registry, candidate at 0.50 raises PromotionRejected naming the floor and the value (today this silently succeeds - this is the failing test that motivates the slice)
- tests/test_model_registry.py::test_promote_accepts_first_model_at_floor - empty registry, candidate exactly at MIN_DIRECTIONAL_ACCURACY promotes and becomes active (boundary is inclusive)
- tests/test_model_registry.py::test_promote_rejects_below_floor_even_when_beating_incumbent - incumbent 0.45, candidate 0.49 -> still rejected; floor and incumbent checks are independent
- tests/test_model_registry.py::test_floor_applies_with_promotion_decision - a decide() verdict of promote=True does not bypass the floor for a sub-floor candidate
- tests/test_model_registry.py::test_rejected_below_floor_is_recorded - the rejection appears in registry.json's 'rejected' list with the floor named in the reason
- tests/test_model_registry.py::test_rejected_promotion_leaves_active_and_history_untouched - after a floor rejection the previous active version, history list and index file are byte-identical to before
- tests/test_health_endpoint.py::test_health_floor_matches_registry_constant - the floor reported/applied by the health surface is registry.MIN_DIRECTIONAL_ACCURACY, not a duplicated literal

### 4. Slice 4: daily model - aggregated 1d bars, trained, registered per interval, and served

Closes R1's daily half without live Binance access.

(1) Daily bars from stored history. scripts/train_ensemble.py's --interval gains '1d' as a supported value. For '1d' it derives daily bars by aggregating the 4h klines already in the table: open = first, high = max, low = min, close = last, volume = sum, grouped on the UTC calendar day. Binance 4h bars are UTC-aligned at 00/04/08/12/16/20, so six consecutive bars aggregate to exactly the daily bar the exchange would serve - this is aggregation, not synthesis. Any day not containing all six 4h bars is dropped, including the partial trailing day, so no label is ever built on an incomplete bar. The aggregator is a pure function over a DataFrame, unit-testable with hand-built rows.

(2) Per-interval activation. The registry index gains active_by_interval ({'4h': id, '1d': id}); the existing `active` key is retained as the default-interval ('4h') pointer for back-compat with anything already reading it, and promote() writes both. A 1d candidate is gated against the 1d incumbent (and the Slice 3 floor), never against the 4h model. load_active(registry_root, interval=None) selects by interval and re-validates that the loaded manifest's interval matches what was asked for; asking for '1d' against a registry holding only 4h returns None rather than the 4h model.

(3) Serving. app/services/signal_service.py keys its predictor cache by interval. The signal endpoint accepts an optional `horizon` query param, default '4h'. An unrecognised horizon is a 400 naming the supported values (validated through Slice 1's interval_delta). A recognised horizon with no registered model for it is an explicit error naming the missing model - never a silent fall-through to the baseline EMA rule labelled with that horizon. Candle fetch, staleness window and the response's `horizon` field all follow the requested interval, and Slice 1's mismatch guard proves the right model saw the right bars.

HONEST LIMIT, to be stated in the issue and in the release notes: this slice trains, registers and serves a 1d model from stored history. It does NOT enable live 1d ingestion - docker-compose.prod.yml:90 streams 4h only, and while Binance returns HTTP 451 to this VPS no new klines of any interval are arriving (the table is stale since 2026-07-31). Leaving the 1d stream off is the fail-closed choice, not a completed one, and the daily model will go stale on the same clock as the 4h one until the 451 is resolved. Do not describe 1d ingestion as verified.

**Acceptance**

- [ ] The 4h-to-daily aggregator is a pure function; days with fewer than six 4h bars, including the trailing partial day, are excluded from training data.
- [ ] `python scripts/train_ensemble.py --interval 1d` runs against the existing klines table and produces a manifest whose interval is '1d', with no network access and no schema migration.
- [ ] The registry tracks an active version per interval; the legacy `active` key still resolves to the 4h model so existing readers are unaffected.
- [ ] A 1d candidate is compared only against the 1d incumbent and the Slice 3 floor; promoting or rejecting a 1d model never mutates the active 4h pointer.
- [ ] load_active(root, interval=X) returns a predictor whose manifest interval is exactly X, or None - it never substitutes a model of a different interval.
- [ ] The signal endpoint's horizon param defaults to '4h'; an unknown value is a 400, and a known value with no registered model is an explicit named error. No response is ever a baseline signal labelled with a horizon whose model does not exist.
- [ ] The response's horizon field, the candles requested and the staleness window all follow the requested interval; Slice 1's IntervalMismatchError does not fire on any passing test.
- [ ] No 1d ingestion stream is added to docker-compose.prod.yml, and the issue, PR and release notes all state plainly that live 1d ingestion is unverified and blocked by the Binance HTTP 451 on this VPS.
- [ ] The whole slice's test suite passes offline against tmp_path fixtures and hand-built candle frames.

**Tests first**

- tests/test_train_ensemble.py::test_aggregate_4h_to_daily_ohlcv - six hand-built UTC-aligned 4h bars produce one daily bar with first open, max high, min low, last close and summed volume
- tests/test_train_ensemble.py::test_aggregate_drops_partial_trailing_day - a final day with fewer than six bars is excluded from the output
- tests/test_train_ensemble.py::test_aggregate_drops_days_with_gaps - a mid-series day missing one 4h bar is dropped rather than aggregated from five bars
- tests/test_train_ensemble.py::test_aggregate_is_pure - the input DataFrame is not mutated and repeated calls return equal output
- tests/test_ensemble_trainer.py::test_daily_run_records_interval_1d_in_manifest - a --interval 1d run writes manifest['interval'] == '1d'
- tests/test_model_registry.py::test_active_version_tracked_per_interval - promoting a 1d version leaves the active 4h version untouched, and each interval resolves to its own version id
- tests/test_model_registry.py::test_legacy_active_key_still_points_at_4h - the pre-existing `active` key continues to name the 4h model after a 1d promotion (back-compat)
- tests/test_model_registry.py::test_1d_candidate_gated_against_1d_incumbent_not_4h - a 1d candidate above the floor promotes despite a higher-scoring 4h incumbent, and a sub-floor 1d candidate is rejected without disturbing the active 4h model
- tests/test_ensemble_predictor.py::test_load_active_selects_by_interval - load_active(root, interval='1d') returns the 1d predictor from a registry holding both
- tests/test_ensemble_predictor.py::test_load_active_returns_none_for_unregistered_interval - load_active(root, interval='1d') against a 4h-only registry returns None and never the 4h predictor
- tests/test_signal_service.py::test_staleness_window_follows_requested_interval - for a 1d predictor a candle 2 days and 1 minute past close is stale while 47 hours is not (injected `now`, matching the existing deterministic _is_stale tests)
- tests/test_signal_service.py::test_predictor_cache_is_keyed_by_interval - '4h' and '1d' resolve to distinct predictors and neither leaks into the other's slot
- tests/test_signal_endpoint.py::test_signal_serves_daily_model_for_1d_request - fixture registry with both models; horizon=1d returns the 1d version_id, horizon '1d', and votes from xgboost/lightgbm/catboost (mirrors the existing 4h test at tests/test_signal_endpoint.py:122-158)
- tests/test_signal_endpoint.py::test_unknown_horizon_returns_400 - horizon=1h returns 400 naming the supported intervals
- tests/test_signal_endpoint.py::test_horizon_without_registered_model_is_explicit_error - horizon=1d against a 4h-only registry returns an error naming the missing 1d model and never a 200 carrying baseline-momentum-v0 with horizon '1d'
