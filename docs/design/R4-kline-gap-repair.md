# R4 — Kline ingestion: automatic gap detection and repair

> **PRD requirement.** Binance kline ingestion (REST backfill + websocket keep-current) into PostgreSQL.

Status: designed, not yet implemented. Produced by a design council of two
independent designs judged head to head.

## Chosen approach

Design A (3-slice, no-new-services: coverage summariser -> repair_gaps() -> --repair cron mode), grafted with Design B's window-bounded coverage maths, gap chunking, deploy_prod.sh cron registration, and a trimmed, default-off training-coverage stamp.

## Rationale

Fit with existing patterns decides it. /Users/isupercoder/Code/github/ai-forecasting/app/api/v1/endpoints/health.py runs its own `await db.execute(text(...))` against the async session and then hands the raw scalar to a PURE function (`market_data_status(newest, interval=...)`, `backup_status(dir, now=...)`). Design B's `coverage_report(engine, ...)` takes a sync SQLAlchemy Engine, which the async health path does not have and cannot cleanly obtain, so B's slice 1 would either bolt a second engine into the request path or get quietly refactored during implementation. Design A's pure summariser matches the house shape exactly and lands in a small `app/services/*_status.py`-style module alongside the two that already exist. Design A also names the real production failure honestly: GeoBlockedError as a first-class outcome, "blocked" as a status distinct from "clean", so a 451-era run never reports success. Where B is better and is grafted in: (1) coverage must be computed against a WINDOW (expected bars vs stored bars), not from find_gaps() output, because a still-ongoing outage is a trailing gap with no right-hand candle and find_gaps() returns [] for it - this is the exact case in production right now; (2) the window form is a single cheap SQL aggregate (COUNT/MIN/MAX), which kills A's own risk #3 (find_gaps pulls every open_time into Python on every health poll) and B's matching risk - detailed gap enumeration stays in the repair script where a table scan is fine; (3) gaps wider than PAGE_LIMIT=1000 bars need explicit chunking, since a multi-day 4h outage is small but a 1h-interval or long outage is not; (4) the cron entry goes through /Users/isupercoder/Code/github/ai-forecasting/scripts/deploy_prod.sh so it is reproducible rather than hand-typed host state, otherwise slice 3 reverts to exactly the "nothing ever runs it" bug being fixed. B's slice 4 (hard fail-closed training gate) is scope-cut: it would block all model refreshes on the current production database, which HAS the hole and cannot be repaired while 451 persists. It survives only as a default-off metadata stamp so "which models trained on holed data" becomes provable without stopping the pipeline. Slice 1 delivers value the day it merges with zero Binance access: the permanent hole becomes a number on /health/detailed.

## Grafted, and explicitly rejected

- From B: coverage must be WINDOW-bounded (expected bars vs stored bars over [window_start, last closed bar]), not derived from find_gaps() output - a still-ongoing outage is a trailing gap with no right-hand candle, which is precisely the live production case find_gaps() reports as zero gaps.
- Extends both designs: compute health-path coverage from a single SQL aggregate (COUNT/MIN/MAX over the window) instead of enumerating gaps. Eliminates A's risk #3 and B's matching risk (pulling every open_time_ms into Python on each poll) and keeps the endpoint O(1). Full gap enumeration stays in the repair script, where a scan is cheap and runs nightly.
- From B: repair must chunk gaps wider than PAGE_LIMIT=1000 bars and assert EXACT candle counts at gap boundaries (Binance startTime is inclusive) - off-by-one at gap edges is the likeliest correctness bug and 'no gaps remaining' does not catch it.
- From B: repair re-enumerates gaps from the database AFTER writing and reports what actually remains, rather than trusting the write path.
- From B: the cron entry is installed idempotently by scripts/deploy_prod.sh, not hand-added to the host, so it cannot drift back to 'nothing ever runs it'.
- From B: repair distinguishes 'partial' (upstream returned fewer candles than the gap - the venue genuinely lacks data) from 'blocked' (upstream refused), so legitimately-missing candles do not masquerade as an outage forever.
- From B slice 4, scope-cut: coverage is stamped into model metadata and warned about by default; the hard fail-closed training gate ships behind an opt-in flag, because enabling it now would block all model refreshes on a production database whose hole cannot be repaired while Binance returns 451.
- Rejected from B: coverage_report(engine, ...) living in kline_store.py. health.py is async and holds an AsyncSession, not a sync Engine; the pure-function-plus-caller-owned-query shape of market_data_status/backup_status is the pattern that already works there.
- Rejected from A: sourcing the health component from find_gaps() per pair per request.
- Kept from A: GeoBlockedError as a named, non-crashing outcome and 'blocked' as a status distinct from clean/partial - the single most important honesty property while the VPS is 451-blocked.

## Acceptance criteria

- [ ] Every slice is TDD: the listed tests are written first, fail for the stated reason, then the implementation makes them pass. No slice merges with a red or skipped test.
- [ ] No new services, containers, compose entries, schedulers, or third-party dependencies. Execution reuses the host cron that already runs scripts/prod_backup.py; deploys stay gated by scripts/ci_gate.py; each slice is cut with scripts/release.py.
- [ ] Every slice is testable and provable with Binance geo-blocked (HTTP 451): all fetches are injected in tests, all DB work runs on SQLite, no test requires network.
- [ ] Fail-closed everywhere: an undeterminable coverage answer reports 'unknown', a blocked repair reports 'blocked', and neither is ever rendered as healthy or as success.
- [ ] The current production outage (klines stale since 2026-07-31) is visible as a non-healthy component on /health/detailed after slice 1 ships, without any Binance access.
- [ ] No health request performs a full table scan of klines: coverage comes from a single bounded SQL aggregate, not from find_gaps().
- [ ] Repair is idempotent and crash-resumable: it recomputes gaps from the database on every invocation and never caches a plan across runs.
- [ ] Repair never claims success it did not achieve; partial fills leave remaining gaps reported and the run non-clean.
- [ ] The scheduled repair leaves a persisted trace that /health/detailed reads, so 'the cron was never installed' degrades health instead of passing silently.
- [ ] The cron entry is written by scripts/deploy_prod.sh, not by hand, so it is reproducible across redeploys.

## Delivery slices

### 1. Slice 1: klines coverage becomes a reported component on /health/detailed

Problem: app/services/kline_store.py find_gaps() only detects INTERIOR holes - it compares consecutive stored candles, so an outage that is still ongoing (the current one, klines stale since 2026-07-31) has no right-hand candle and reports zero gaps. The hole is therefore invisible. Fix: add a new pure module /Users/isupercoder/Code/github/ai-forecasting/app/services/kline_coverage.py with `coverage_status(stored_bars, oldest_open_time_ms, newest_open_time_ms, interval, window_start_ms, now_ms) -> dict`, mirroring the shape and purity of the existing app/services/market_data_status.py and app/services/backup_status.py. It computes expected_bars = the count of CLOSED bars on the interval grid in [window_start_ms, last_closed_bar(now_ms)], missing_bars = expected_bars - stored_bars, and returns {status, message, interval, window_days, expected_bars, stored_bars, missing_bars, coverage_pct, newest_kline}. Status: 'healthy' when missing_bars == 0; 'degraded' when missing_bars > 0; 'missing' when stored_bars == 0; 'unknown' when inputs are unusable. Because it is window-bounded it counts leading, interior AND trailing holes, so the live 451 outage reports degraded. Export DEGRADED_STATUSES from the module (the pattern backup_status.py already established, so renaming a status cannot silently leave health green). Wire it into /Users/isupercoder/Code/github/ai-forecasting/app/api/v1/endpoints/health.py next to the existing market_data block, using the SAME shape: health runs one cheap aggregate `SELECT COUNT(*), MIN(open_time_ms), MAX(open_time_ms) FROM klines WHERE pair=:pair AND "interval"=:interval AND open_time_ms >= :window_start` and passes the scalars to the pure function. NO call to find_gaps() from the request path - that pulls every open_time into Python. Config via env: MARKET_DATA_INTERVAL (already used), KLINE_COVERAGE_PAIR (default the primary universe pair), KLINE_COVERAGE_DAYS (default 30). Any exception -> component status 'unknown' with the message, never healthy. Scope guard: this slice reports only. It repairs nothing and touches neither kline_backfill.py nor the backfill script.

**Acceptance**

- [ ] app/services/kline_coverage.py contains no database, network, or filesystem access - it is a pure function over scalars, callable from the async request path with no engine.
- [ ] A stale-but-hole-free table (the exact current production shape) reports 'degraded', proving the trailing-gap case that find_gaps() misses.
- [ ] /health/detailed gains components.klines_coverage and degrades the top-level status via the module's exported DEGRADED_STATUSES, not a literal restated in health.py.
- [ ] The health path performs one bounded aggregate query; no full scan of open_time_ms, no per-pair loop over the universe.
- [ ] A failing or unavailable query yields 'unknown', never 'healthy'.
- [ ] Deployed against the current production database, /health/detailed shows a non-zero missing_bars for the 2026-07-31 outage with no Binance access required.

**Tests first**

- tests/test_kline_coverage.py: contiguous candles covering the whole window, newest is the last closed bar -> status 'healthy', missing_bars 0, coverage_pct 100.0
- tests/test_kline_coverage.py: one interior hole of 3 bars in a 4h window -> status 'degraded', missing_bars 3
- tests/test_kline_coverage.py: REGRESSION GUARD for the live outage - newest candle 5 days old, no interior holes at all (find_gaps() would return []) -> status 'degraded' with missing_bars equal to the number of closed bars since the newest one
- tests/test_kline_coverage.py: newest candle is the currently-OPEN (unclosed) bar -> healthy, no off-by-one trailing gap
- tests/test_kline_coverage.py: stored_bars == 0 -> status 'missing', not 'healthy' and not a crash
- tests/test_kline_coverage.py: window starts before the oldest stored candle -> leading shortfall counted in missing_bars
- tests/test_kline_coverage.py: stored_bars > expected_bars (off-grid/duplicate rows) -> status 'unknown' with an explanatory message, never a negative missing_bars
- tests/test_kline_coverage.py: unknown interval string -> status 'unknown', no KeyError escapes
- tests/test_kline_coverage.py (integration, SQLite): create_tables + upsert_klines a series with a hole, run the same aggregate query health uses, feed coverage_status -> missing_bars matches the hole exactly
- tests/test_endpoints_health.py: /health/detailed exposes components.klines_coverage with expected_bars/stored_bars/missing_bars
- tests/test_endpoints_health.py: degraded coverage sets top-level status 'degraded'
- tests/test_endpoints_health.py: the coverage query raising -> component status 'unknown' AND top-level status is not 'healthy'
- tests/test_endpoints_health.py: the coverage block issues exactly one SQL statement and does not call find_gaps()

### 2. Slice 2: repair_gaps() turns detected gaps into bounded, verified, fail-closed backfill

Problem: app/services/kline_backfill.py backfill() can fill an arbitrary [start_ms, end_ms) range, but no code path ever computes a gap and calls it, so every ingestor outage leaves a permanent hole. Fix: add `repair_gaps(fetch, engine, pair, interval, window_start_ms, now_ms=None, max_gaps=20, max_candles=50_000) -> dict` to app/services/kline_backfill.py. It (1) enumerates gaps for the window: find_gaps() for interior holes, PLUS a synthesised leading gap (window_start -> oldest stored) and trailing gap (newest+step -> last closed bar) - the two find_gaps() structurally cannot see; (2) calls the existing backfill(fetch, engine, pair, interval, start_ms=gap_start, end_ms=gap_end) per gap, letting backfill's own pagination handle gaps wider than PAGE_LIMIT=1000 bars; (3) RE-ENUMERATES gaps from the database afterwards and reports what is actually left; (4) returns {pair, interval, gaps_found, gaps_repaired, candles_written, remaining_gaps, status, error} with status in {'clean' (nothing to do), 'repaired' (all closed), 'partial' (bounded out or short data), 'blocked' (upstream refused)}. Also add `PermanentFetchError` and `GeoBlockedError(PermanentFetchError)` to the module and raise GeoBlockedError from fetch_binance_page on HTTP 451/403 - today those fall through to response.raise_for_status() and surface as a raw httpx.HTTPStatusError that kills the run. repair_gaps catches GeoBlockedError, stops immediately (further pairs are pointless), and returns status 'blocked' with remaining_gaps intact and the error text preserved. Bounded by max_gaps/max_candles per invocation so the first run after a long outage cannot storm Binance into 429s; gaps are recomputed from the DB every call, never cached across runs, so it is idempotent and crash-resumable on top of upsert_klines' on_conflict_do_nothing. Scope guard: library function only. No CLI, no cron, no health changes.

**Acceptance**

- [ ] repair_gaps takes an injected fetch and works end-to-end on SQLite with no network; the whole slice is provable while Binance returns 451.
- [ ] Leading and trailing gaps are repaired, not just the interior ones find_gaps() can see.
- [ ] A geo-blocked upstream produces status 'blocked' - never 'clean', never an unhandled exception, never a partial-success claim.
- [ ] fetch_binance_page maps 451/403 to GeoBlockedError while leaving the existing 429/418/5xx TransientFetchError behaviour untouched.
- [ ] Repair recomputes gaps from the database on entry AND re-verifies after writing; no plan is cached between invocations.
- [ ] Boundary correctness is asserted by exact candle counts at gap edges (Binance startTime is inclusive), not by 'no gaps remaining' alone.
- [ ] Re-running a completed repair writes zero rows and calls fetch zero times.

**Tests first**

- tests/test_kline_backfill.py: DB with one 3-candle interior hole + fake fetch serving those candles -> gaps_repaired 1, remaining_gaps 0, candles_written 3, and find_gaps() afterwards returns []
- tests/test_kline_backfill.py: trailing gap only (stale newest, no interior holes) -> repaired up to the last CLOSED bar and not one bar beyond it (assert exact candle count, not just 'no gaps remaining')
- tests/test_kline_backfill.py: leading gap (oldest stored is after window_start) -> repaired back to window_start
- tests/test_kline_backfill.py: gap spanning 2500 bars -> multiple fetch pages, all 2500 bars written, remaining_gaps 0 (PAGE_LIMIT boundary)
- tests/test_kline_backfill.py: fetch raising GeoBlockedError -> status 'blocked', candles_written 0, remaining_gaps unchanged, error text present, no exception escapes
- tests/test_kline_backfill.py: fetch_binance_page against a stubbed HTTP 451 response raises GeoBlockedError, not httpx.HTTPStatusError (regression guard for the live production failure mode)
- tests/test_kline_backfill.py: fetch_binance_page against a stubbed HTTP 403 raises GeoBlockedError; 429/418/5xx still raise TransientFetchError as before
- tests/test_kline_backfill.py: fetch returns FEWER candles than the gap (venue genuinely has no data) -> status 'partial', remaining_gaps > 0, nothing silently swallowed
- tests/test_kline_backfill.py: two gaps with max_gaps=1 -> only the first repaired, remaining_gaps 1; a second call repairs the rest (resumability)
- tests/test_kline_backfill.py: max_candles cap stops mid-run and reports 'partial' rather than exceeding the cap
- tests/test_kline_backfill.py: fully complete window -> status 'clean' and fetch is NEVER called
- tests/test_kline_backfill.py: running repair twice over the same gap writes zero extra rows the second time (upsert idempotence)
- tests/test_kline_backfill.py: a mid-gap TransientFetchError still retries via the existing bounded path; exhausting retries leaves earlier gaps' candles persisted and reports 'partial'

### 3. Slice 3: scripts/backfill_klines.py --repair, run by the existing host cron, with a trace health can see

Problem: /Users/isupercoder/Code/github/ai-forecasting/scripts/backfill_klines.py is invoked by nothing - not docker-compose.prod.yml, not cron, not deploy. Fix, reusing the host cron that already runs scripts/prod_backup.py: add a `--repair` mode to scripts/backfill_klines.py that runs repair_gaps() for every pair in UNIVERSE at the configured interval over a rolling window (--years, existing flag), prints one report line per pair, and exits 0 = all clean/repaired, 1 = gaps remain (partial), 2 = blocked upstream, so cron mail and any wrapper can tell the three apart. It writes a single JSON audit record per run - path from KLINE_REPAIR_STATUS_DIR, mirroring exactly how BACKUP_STATUS_DIR and app/services/backup_status.py already work - containing {run_at, interval, window_days, status, pairs: [{pair, gaps_found, gaps_repaired, candles_written, remaining_gaps, status}]}. The record is written on EVERY run, clean or blocked: it is proof the cron fired, not just proof of failure. Add `repair_status(directory, now=None, max_age_hours=26)` to app/services/kline_coverage.py in the same shape as backup_status(), and fold last_repair_at / last_repair_status / repair_age_hours into the klines_coverage health component from slice 1: missing record or record older than 26h -> degraded with a 'gap repair has not run' message. That is the guard against this script quietly going un-invoked AGAIN. Register the cron line from scripts/deploy_prod.sh (idempotently, next to the existing prod_backup.py entry) so it is reproducible instead of hand-typed host state that drifts; mount the status dir read-only into the API container in docker-compose.prod.yml the same way the backup dir already is. No new container, no compose service, no scheduler dependency.

**Acceptance**

- [ ] A single documented command repairs klines gaps across the universe and is actually scheduled - the R4 'nothing runs it' gap is closed.
- [ ] Exit codes distinguish clean (0), gaps remaining (1) and upstream blocked (2); a blocked run is never exit 0.
- [ ] An audit record is written on every run and read by /health/detailed, so a cron that was never installed shows up as degraded rather than as silence.
- [ ] The cron entry is created by scripts/deploy_prod.sh idempotently (re-running deploy does not duplicate it), and the status dir is mounted read-only into the API container in docker-compose.prod.yml.
- [ ] Run today against production, the script exits 2, records status 'blocked' per pair, and the hole stays visible - honest monitoring, no false green.
- [ ] The day Binance egress is restored, the same unchanged cron closes the hole with no manual intervention.

**Tests first**

- tests/test_backfill_script.py: --repair with a seeded gap and a stubbed fetch repairs it and exits 0
- tests/test_backfill_script.py: gaps remaining after a capped run -> exit code 1
- tests/test_backfill_script.py: geo-blocked fetch -> exit code 2 and a line in stdout naming the pair and 'blocked'
- tests/test_backfill_script.py: clean run -> exit 0 AND the audit record is still written (proof of the run, not only of failure)
- tests/test_backfill_script.py: audit record contains one entry per UNIVERSE pair with the documented schema keys
- tests/test_backfill_script.py: --repair with an unreachable DATABASE_URL exits non-zero rather than silently succeeding
- tests/test_backfill_script.py: --repair does NOT perform a full historical backfill - assert fetch call ranges stay inside the detected gaps
- tests/test_backfill_script.py: --repair leaves the existing default (non-repair) backfill behaviour unchanged
- tests/test_kline_coverage.py: repair_status with a record younger than 26h -> 'healthy'; older -> 'stale'
- tests/test_kline_coverage.py: repair_status with a missing directory/record -> 'missing', never 'healthy'
- tests/test_kline_coverage.py: repair_status with unset directory -> 'not_configured' (local dev has none), which does not degrade health
- tests/test_endpoints_health.py: klines_coverage surfaces last_repair_at, last_repair_status and repair_age_hours
- tests/test_endpoints_health.py: a stale repair record degrades /health/detailed even when missing_bars is 0

### 4. Slice 4 (last, default-off): stamp data coverage into model metadata so holed training is provable

Problem: models train on whatever is in klines, so a model trained across the 2026-07-31 hole is indistinguishable from a clean one after the fact. Scope-cut deliberately: this slice does NOT hard-block training. A hard fail-closed gate would stop every model refresh on the current production database, which contains a hole that CANNOT be repaired while Binance returns 451 - that would be the fix causing a worse outage than the bug. Fix: before training, /Users/isupercoder/Code/github/ai-forecasting/scripts/train_models.py and scripts/train_ensemble.py compute the slice-1 coverage over the training window and (a) print a prominent warning when missing_bars > 0, (b) stamp {expected_bars, stored_bars, missing_bars, coverage_pct, window} into the model metadata written to the registry. An opt-in --require-complete-data flag (default OFF) aborts with a non-zero exit and writes no model when missing_bars exceeds --coverage-tolerance (default 0). Turn the flag on in the deploy path only after slice 3 has reported a clean repair. Existing registry entries without coverage metadata must still load.

**Acceptance**

- [ ] Any model in the registry can be traced to the data coverage it was trained on.
- [ ] Default behaviour does not block training, so shipping this slice cannot halt model refreshes while Binance is geo-blocked.
- [ ] The strict gate exists behind an explicit flag and is only enabled once slice 3 reports a clean repair.
- [ ] No new dependencies; coverage is computed by the slice-1 function, not a second implementation.

**Tests first**

- tests/test_train_coverage_stamp.py: training over a holed window succeeds by default, emits the warning, and the written metadata carries missing_bars > 0
- tests/test_train_coverage_stamp.py: training over a complete window writes metadata with missing_bars == 0 and coverage_pct 100.0
- tests/test_train_coverage_stamp.py: --require-complete-data with a holed window -> non-zero exit and NO model file written
- tests/test_train_coverage_stamp.py: --require-complete-data with --coverage-tolerance set above the shortfall -> proceeds, and the tolerance override is recorded in the metadata
- tests/test_train_coverage_stamp.py: an existing registry entry with no coverage metadata still loads (backward compatible, no KeyError)
