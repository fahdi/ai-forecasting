# R13 — Audit log of every signal and every decision

> **PRD requirement.** Audit log in PostgreSQL: every signal, every decision (entered / skipped and why), every order and fill.

Status: designed, not yet implemented. Produced by a design council of three
independent designs judged against each other; this document records the chosen
approach, why, and what was taken from the runners-up.

## Chosen approach

Design 3 ("HTTP decision-post from strategy to existing API, thinnest-first"), with grafts from Design 2 (structured non-short-circuit guard evaluation in a pure module, insert-only semantics, runmode gate, signalled-vs-executed) and Design 1 (import-order regression test, capped/paginated reads, exhaustive UI label test).

## Rationale

All three converge on the same transport, and the code backs it: the strategy already speaks HTTP to the API every candle via SignalClient (user_data/strategies/signal_client.py:52-68) over SIGNAL_API_URL, already wired at docker-compose.prod.yml:109, and the freqtrade container deliberately holds no DATABASE_URL (docker-compose.prod.yml:105-116). So transport is settled; the designs separate on sequencing, safety semantics, and cost.

Design 3 wins on first-slice value and fail-closed defaults. Its first slice ships table + endpoint + recorder + strategy wiring, so decisions reach Postgres immediately; Design 1's slice 1 says "nothing calls it yet" (schema only), and Design 2 spends slices 2-3 on a table and a spooling thread before one real decision is captured. Decisions not recorded today cannot be backfilled — that argues hard for the write path first. Design 3 alone token-gates the write endpoint from day one; Design 1 leaves POST unauthenticated until slice 7 on an API whose dashboard proxy already forwards POST (frontend/src/app/api/upstream/signal/[...path]/route.ts:46-48). Design 3 alone addresses R13's third clause "every order and fill" (docs/PRD-trading-bot.md:125-126) with reconciliation, and alone caught that the strategy CI job runs only tests/test_ensemble_strategy.py (.github/workflows/ci.yml:65), so recorder fail-safe tests would silently never run — the exact hole that job's comment at lines 39-42 exists to close.

Design 2 has the best ideas but the worst cost/benefit: an NDJSON spool with rotation and replay, heartbeat rows, and a coverage endpoint that derives expected counts from klines — which are stale from the Binance 451 block, so the freshest failure mode makes the detector report "unknown". Its spool guards against losing rows during an API outage, but api and freqtrade sit on the same compose network: if the API is down there are no signals either, so every lost row would have said no_signal. That is the least informative row in the vocabulary. Its record_prediction bool -> Optional[int] change also breaks a tested contract (app/services/model_health.py:48-90) for a drill-down nobody has asked for.

Two claims in the designs are wrong or weak and I overrode them. (1) Design 3 stores pair as "BTC/USDT" (freqtrade form) while prediction_log stores the exchange symbol "BTCUSDT" (app/services/model_health.py:33, app/services/signal_service.py:21-26) — that silently breaks the join between the two halves of R13. The final plan normalizes server-side via normalize_pair (signal_service.py:137). (2) Design 3's last-write-wins upsert and Design 1's ON CONFLICT DO NOTHING both destroy information: an audit log that can be overwritten is not an audit log, and first-write-wins loses the decision that actually governed the candle. The final plan is insert-only with a content-addressed decision_uid, so a repeat evaluation with the same outcome dedupes and one with a different outcome inserts a second row.

On the latency objection all three raise: it is smaller than they think. SignalClient already blocks up to 5.0s per pair per candle (signal_client.py:22,55) and the strategy already accepts that. A 1.0s POST is strictly less than the blocking already in the loop, on a 1h timeframe. So the non-blocking upgrade is a trigger-driven optimisation (slice 6), not a prerequisite — which is why Design 2's slice-3 threading is premature and Design 3's ordering is right.

Fail-safety in the final plan is structural, not defensive: the pure evaluator returns data, the dataframe is mutated from that data, and only then is the recorder called, inside its own try/except, from a client that never raises. An ordered-mock test locks the ordering so no future refactor can make the audit path an input to the trading path.

## Grafted from the runners-up

- From Design 2: extract guard evaluation into a pure user_data/strategies/decision.py with no freqtrade import, returning a structured EntryDecision instead of a bool. It runs in both CI venvs and makes the strategy edit in the write slice trivial.
- From Design 2: evaluate ALL guards rather than short-circuiting, and store the full list in a guards JSON column while keeping a scalar reason = first blocking guard. Gives counterfactual analysis ('would it have entered but for volatility?') for a few float comparisons.
- From Design 2: gate emission on dp.runmode in (live, dry_run) with an explicit test asserting zero rows in backtest/hyperopt, or populate_entry_trend writes tens of thousands of junk rows during a hyperopt run.
- From Design 2: insert-only. No UPDATE or DELETE path anywhere in the service or endpoint module, asserted by a test. Server assigns recorded_at_ms; a client-supplied value is ignored.
- From Design 2: confirm_trade_entry to distinguish 'the strategy signalled' from 'freqtrade actually entered'. With max_open_trades=3 (user_data/config.dry.json:16) and 4 pairs, a signalled entry can be dropped by slot exhaustion, protections, or pair locks, and that gap is invisible today.
- From Design 2 (fixed): make decision_uid content-addressed over the outcome, not over thresholds. Design 2's own key collapses two genuinely different evaluations of one candle; hashing pair|side|candle|decision|reason|strategy_version dedupes restart re-analysis while preserving a genuine change of mind.
- From Design 1: an explicit test that create_tables(engine) on a fresh engine yields BOTH prediction_log and decision_log, guarding the import-order trap already documented at app/api/v1/endpoints/models.py:34-37.
- From Design 1: capped, keyset-paginated reads with an indexed predicate from day one, so decision_log does not repeat the unfiltered select(prediction_log) full-table scan at app/services/model_health.py:178 and app/api/v1/endpoints/chart.py:148-152.
- From Design 1: a frontend test that iterates the full reason vocabulary and fails when any code lacks a plain-language label, so backend/frontend drift breaks CI instead of leaking a raw slug into the UI.
- From Design 1: write the no-retention decision into docs/RUNBOOK.md with the arithmetic, so a future reader knows the absent cleanup job is a decision rather than an oversight.
- Own addition: declare DECISION_LOG_TOKEN with ${VAR:?set in .env} on both api and freqtrade, matching the existing pattern at docker-compose.prod.yml:22,61,134. This removes Design 3's stated risk that a missing env var silently kills auditing — the stack refuses to start instead.
- Own addition: include the nullable trade_id column in the initial schema even though nothing writes it until the last slice. There is no migration tooling (metadata.create_all at app/services/kline_store.py:45 never alters existing tables; the only precedent is a hand-rolled ALTER at app/core/database.py:129-135), so every column this table will ever need must ship in the first CREATE.
- Explicitly deferred, not dropped: Design 2's record_prediction -> row id and SignalResponse.signal_id foreign key. decision_log already stores what the strategy SAW; a hard FK buys only model_votes/top_features drill-down and costs a tested-contract change.

## Acceptance criteria for the requirement as a whole

- [ ] Completeness: every branch that can block or trigger a trade decision in EnsembleSignalStrategy — 8 entry reasons and 4 exit reasons including both fail-closed except paths — writes a distinct, machine-readable reason to Postgres. A test asserts SELECT DISTINCT reason after the suite equals exactly that vocabulary.
- [ ] Fail-safety, proven not promised: a recorder that raises, hangs, returns 500, or points at a dead host leaves enter_long, exit_long and custom_exit's return value byte-identical to a run with recording disabled, across every scenario in tests/test_ensemble_strategy.py, and nothing raises.
- [ ] Ordering: an ordered-mock test proves the dataframe and the return value are set BEFORE the recorder is invoked, so the audit path can never become an input to the trading path.
- [ ] Bot independence: with the API container stopped, the strategy completes a full candle cycle, produces correct fail-closed no-entry signals, and does not raise. No rows are written and /coverage says so.
- [ ] Answerability: for any pair and candle, one request (or one psql query) returns the reason, the full guard array with values and thresholds, the signal the strategy saw, the thresholds in force, close, ema50 and volatility — enough to reconstruct the decision with no log file.
- [ ] Joinability: decision_log.pair holds the exchange symbol, so the decision half and the signal half of R13 (prediction_log, app/services/model_health.py:31) join on pair without translation.
- [ ] Insert-only: no UPDATE or DELETE path exists against decision_log anywhere in the codebase (asserted by an AST test), and recorded_at_ms is always server-assigned.
- [ ] No backtest pollution: runmode='backtest' emits zero rows, asserted by a test, so a hyperopt run cannot write tens of thousands of junk rows.
- [ ] Honest coverage: /api/v1/decisions/coverage reports receiving=false within 2 hours of the bot going silent, computes expected counts from wall clock rather than klines, and stays truthful while market data is stale.
- [ ] Honest UI: an empty decision log renders 'no decisions recorded' with the age of the last one, never a blank table; 'audit unavailable' is distinct from 'nothing in this window'; no reason code or technical jargon reaches user-facing text.
- [ ] Bounded reads: no read endpoint returns more than 500 rows or issues a query without both a LIMIT and an indexed predicate — decision_log does not repeat the unfiltered select(prediction_log) scan at app/services/model_health.py:178 and app/api/v1/endpoints/chart.py:148-152.
- [ ] Fail-closed ingest: POST /api/v1/decisions rejects a missing or wrong token with 401 and writes nothing, and returns 503 with no write when the token is unconfigured. DECISION_LOG_TOKEN is a required compose variable on both api and freqtrade, so the stack cannot start in a silently non-auditing state.
- [ ] Durability: decision_log is inside the nightly pg_dump and is asserted by the restore drill (scripts/prod_backup.py:84, min_tables raised 5 -> 6), and the freqtrade trade sqlite joins the backup set in the final slice.
- [ ] Retention: no purge, TTL, or partitioning job exists anywhere in the repo, and docs/RUNBOOK.md states this as a decision with the ~70k rows / ~15 MB per year arithmetic behind it.
- [ ] CI: new tests land in all three jobs — backend (table, endpoints, evaluator), strategy (recorder and guard-to-reason mapping, with the pytest invocation at .github/workflows/ci.yml:65 extended past test_ensemble_strategy.py so they cannot silently skip), frontend (label exhaustiveness, coverage states). scripts/ci_gate.py continues to block deploys of non-green commits.
- [ ] PRODUCTION HONESTY: R13 is not marked done on a green deploy. freqtrade is down and Binance returns 451 to this host, so a correct implementation will record zero rows until the bot is restarted, and every row it then records will legitimately read no_signal or stale_signal until market data flows. Done means rows observed in production Postgres, and the dashboard must render that state as 'not recording' rather than as a quiet market.

## Delivery slices

Each slice is independently shippable and independently valuable, and becomes
its own GitHub issue and its own release.

### 1. R13-1: Guard evaluation returns structured data (pure module, no I/O, no schema)

Extract the guard chain from EnsembleSignalStrategy._entry_allowed (user_data/strategies/EnsembleSignalStrategy.py:149-178) into a new pure module user_data/strategies/decision.py exposing evaluate_entry(signal, close, ema50, volatility_ann, confidence_threshold, volatility_ceiling) -> EntryDecision and evaluate_exit(signal, exit_confidence_threshold) -> ExitDecision. EntryDecision carries decision ('entered'|'skipped'), reason (first failing guard, preserving the existing short-circuit ORDER as the reported reason), guards (list of {name, passed, value, threshold}), and context (close, ema50, volatility_ann, thresholds, signal fields). All guards are EVALUATED even after one fails; guards that depend on an absent signal are recorded with passed=None and note='not_evaluated', while trend and volatility guards are always evaluated because they read only the dataframe. The module imports stdlib + pandas/numpy only, never freqtrade, so it is importable in the backend venv too. The strategy delegates to it and logs the reason code; trading behaviour is unchanged. REASONS is a frozenset exported from this module and is the single source of the vocabulary. Entry reasons: ok, no_signal, stale_signal, direction_flat, low_confidence, trend_guard, volatility_guard, evaluation_error. Exit reasons: exit_signal, hold, max_hold, evaluation_error.

**Acceptance criteria**

- [ ] user_data/strategies/decision.py contains no freqtrade import and no network or database call; `python -c "import sys; sys.path.append('user_data/strategies'); import decision"` succeeds in the backend venv (python 3.11) as well as .venv-freqtrade (3.12)
- [ ] EnsembleSignalStrategy._entry_allowed and the exit path delegate to decision.py and contain no guard logic of their own
- [ ] enter_long and exit_long columns are identical before and after this change for every scenario in tests/test_ensemble_strategy.py — zero behaviour change
- [ ] Skip lines in the freqtrade log now include the machine reason code, so the stdout log is greppable before any database exists
- [ ] tests/test_decision_evaluation.py runs in BOTH the backend job and the strategy job (.github/workflows/ci.yml). The strategy job's pytest invocation at line 65 is extended to a file list that includes it
- [ ] All three CI jobs green

**Tests to write first**

- tests/test_decision_evaluation.py: evaluate_entry with all guards passing returns decision='entered', reason='ok'
- tests/test_decision_evaluation.py: one test per blocking reason — no_signal, stale_signal, direction_flat, low_confidence, trend_guard, volatility_guard — asserting the exact reason string
- tests/test_decision_evaluation.py: a non-numeric or missing confidence returns reason='low_confidence' and raises nothing (matches the isinstance guard at EnsembleSignalStrategy.py:161)
- tests/test_decision_evaluation.py: NaN ema50 returns 'trend_guard'; NaN volatility_ann returns 'volatility_guard' (matches the pd.isna branches at lines 167 and 171)
- tests/test_decision_evaluation.py: NON-SHORT-CIRCUIT — when confidence fails, the trend and volatility guards are still present in guards[] with real numeric values and thresholds
- tests/test_decision_evaluation.py: signal=None yields reason='no_signal', signal-dependent guards with passed=None and note='not_evaluated', and trend/volatility guards still evaluated
- tests/test_decision_evaluation.py: every guards[] entry carries name, passed, value, threshold (schema lock so the JSON contract cannot drift)
- tests/test_decision_evaluation.py: evaluate_exit returns 'exit_signal' on a confident flat, 'hold' otherwise, and 'hold' when signal is None
- tests/test_decision_evaluation.py: REASONS contains exactly the 8 entry and 4 exit codes and nothing else
- tests/test_ensemble_strategy.py: all 26 existing tests pass unchanged (behaviour-equivalence regression gate)

### 2. R13-2: Entry decisions land in Postgres (table, token-gated ingest endpoint, strategy wiring)

Decisions reach Postgres end to end for the ENTRY side. Adds app/services/decision_log.py defining the decision_log table on the shared app.services.kline_store.metadata (same pattern as prediction_log, app/services/model_health.py:31) plus insert-only record_decisions(engine, rows) -> int using ON CONFLICT DO NOTHING on decision_uid, with the postgresql/sqlite dialect switch copied from upsert_klines (app/services/kline_store.py:52-59). Adds app/api/v1/endpoints/decisions.py with POST /api/v1/decisions (batch <= 32), registered in app/api/v1/api.py, gated on an X-Decision-Token header compared constant-time against DECISION_LOG_TOKEN. Adds `from app.services import decision_log  # noqa: F401` beside the existing model_health import at app/api/v1/endpoints/models.py:37. Adds user_data/strategies/decision_recorder.py (stdlib + requests only, 1.0s timeout, returns False and never raises on any failure, mirroring SignalClient's contract at signal_client.py:52-68). populate_entry_trend (EnsembleSignalStrategy.py:135-147) sets enter_long from the evaluator's decision FIRST, then calls the recorder inside its own try/except; the existing outer except at lines 139-146 records reason='evaluation_error'. Emission is gated on self.dp.runmode in (live, dry_run) so backtest and hyperopt write nothing. STRATEGY_VERSION is sha256 of the strategy + decision + recorder source, first 12 hex, computed at import — the container runs the stock freqtrade image with ./user_data bind-mounted (docker-compose.prod.yml:106,116) so there is no GIT_SHA available.

SCHEMA (decision_log, insert-only): id BigInteger PK; decision_uid String(64) NOT NULL UNIQUE = sha256(pair|side|candle_time_ms|decision|reason|strategy_version)[:32]; pair String(20) NOT NULL (EXCHANGE symbol, normalized server-side via normalize_pair, app/services/signal_service.py:137, so it joins prediction_log.pair); side String(8) NOT NULL ('entry'|'exit'); candle_time_ms BigInteger NOT NULL; decided_at_ms BigInteger NOT NULL (strategy clock); recorded_at_ms BigInteger NOT NULL (SERVER-assigned, client value ignored); decision String(16) NOT NULL ('entered'|'skipped'|'exited'|'held'); reason String(32) NOT NULL; guards JSON NOT NULL; signal_direction String(8) NULL; signal_confidence Float NULL; signal_stale Integer NULL; signal_model_version String(64) NULL; close Float NULL; ema50 Float NULL; volatility_ann Float NULL; confidence_threshold Float NULL; volatility_ceiling Float NULL; strategy_version String(32) NOT NULL; bot_mode String(16) NOT NULL; trade_id Integer NULL (unused until R13-7, included now because there is no migration tooling). CHECK (decision <> 'skipped' OR reason <> 'ok'). Indexes: (pair, side, candle_time_ms), (decided_at_ms DESC), (reason, decided_at_ms DESC).

RETENTION: none, ever. 4 pairs x 2 sides x 24 1h candles = 192 rows/day, ~70k rows and ~15 MB/year. R13 says indefinitely; no purge job is built. decision_log rides the existing whole-database pg_dump (scripts/prod_backup.py:27-32) with no change; verify_restore's min_tables goes 5 -> 6 (scripts/prod_backup.py:84) so the new table is actually asserted by the nightly restore drill.

Ops: DECISION_LOG_TOKEN added to env.example and to BOTH the api and freqtrade services in docker-compose.prod.yml as ${DECISION_LOG_TOKEN:?set in .env}, matching the existing required-secret pattern at lines 22, 61 and 134 — the stack refuses to start rather than auditing silently into the void. docs/RUNBOOK.md line 73 changes from 'Freqtrade log' to 'Postgres decision_log', and §3's 'What's covered' list gains decision_log.

**Acceptance criteria**

- [ ] Every branch that can block an entry in the evaluator, plus the fail-closed except path, produces a distinct reason code recorded in Postgres — 8 entry reasons, no branch reaching production without one
- [ ] A raising, hanging, 500-ing, or dead-host recorder leaves enter_long byte-identical to a run with recording disabled, proven by a test, not asserted in a comment
- [ ] The recorder is provably called after the decision is computed (ordered-mock test), so no future refactor can make the audit path an input to the trading path
- [ ] Given a pair and a candle, one psql query against decision_log returns the reason, the full guards array, the signal the strategy saw (direction, confidence, stale, model_version), the thresholds in force, close, ema50 and volatility — enough to reconstruct the decision without reading any log file
- [ ] decision_log.pair holds the exchange symbol and joins prediction_log.pair; a test asserts a decision and a prediction for the same pair share the identical pair value
- [ ] No code path updates or deletes a decision_log row; recorded_at_ms is always server-assigned
- [ ] docker compose -f docker-compose.prod.yml config fails when DECISION_LOG_TOKEN is unset, so the stack cannot start in a silently non-auditing state
- [ ] docs/RUNBOOK.md §4 row 3 reads 'Postgres decision_log' and §3 'What's covered' lists it; the no-retention decision and the ~70k rows / ~15 MB per year arithmetic are written down
- [ ] The strategy CI job runs tests/test_decision_recorder.py in addition to tests/test_ensemble_strategy.py, so the fail-safe tests cannot silently skip
- [ ] All three CI jobs green; scripts/ci_gate.py blocks the deploy otherwise
- [ ] PRODUCTION CAVEAT, stated on the issue: freqtrade is currently DOWN and Binance returns 451 to this host, so a green deploy will record ZERO rows. This slice is NOT done on deploy — done means rows observed in production Postgres after freqtrade is restarted. Until then, and while klines are stale, every recorded decision will legitimately read no_signal or stale_signal

**Tests to write first**

- tests/test_decision_log.py: create_tables(engine) on a FRESH engine creates both prediction_log and decision_log (guards the import-order trap documented at app/api/v1/endpoints/models.py:34-37)
- tests/test_decision_log.py: record_decisions inserts one row and returns 1; the empty list is a no-op returning 0
- tests/test_decision_log.py: re-recording an identical decision (same uid) inserts nothing and returns 0 — restart re-analysis is idempotent
- tests/test_decision_log.py: re-evaluating the SAME (pair, side, candle) with a DIFFERENT reason inserts a SECOND row; both survive, and the newest by decided_at_ms is the governing decision
- tests/test_decision_log.py: a batch of 3 containing 1 duplicate writes 2 rows
- tests/test_decision_log.py: INSERT-ONLY — an AST scan of app/services/decision_log.py and app/api/v1/endpoints/decisions.py finds no update() or delete() against decision_log
- tests/test_decision_log.py: the CHECK constraint rejects decision='skipped' with reason='ok'
- tests/test_decision_log.py: the three indexes exist on the created table
- tests/test_decisions_endpoint.py: POST with the correct token persists the row and returns {"recorded": n}
- tests/test_decisions_endpoint.py: recorded_at_ms is server-assigned and a client-supplied recorded_at_ms in the body is IGNORED
- tests/test_decisions_endpoint.py: wrong token -> 401 and nothing written; absent header -> 401 and nothing written
- tests/test_decisions_endpoint.py: DECISION_LOG_TOKEN unset -> 503 'decision log not configured' and nothing written (fail-closed, never fail-open)
- tests/test_decisions_endpoint.py: pair 'BTC/USDT', 'btc-usdt' and 'BTCUSDT' all persist as 'BTCUSDT'; a pair outside UNIVERSE -> 422 with the whole batch rejected atomically
- tests/test_decisions_endpoint.py: unknown side or unknown decision -> 422; an UNRECOGNISED reason string is ACCEPTED and stored (dropping audit data is worse than storing a surprise)
- tests/test_decisions_endpoint.py: batch of 32 -> 200; batch of 33 -> 422 and nothing written
- tests/test_decisions_endpoint.py: get_health_engine returning None -> 503, never a 500
- tests/test_decision_recorder.py: record() returns False and does not raise on connection error, on timeout, on HTTP 500, and on an unparseable body (one test each)
- tests/test_decision_recorder.py: the configured timeout is passed to session.post and X-Decision-Token is read from DECISION_LOG_TOKEN
- tests/test_ensemble_strategy.py: one test per entry reason (ok, no_signal, stale_signal, direction_flat, low_confidence, trend_guard, volatility_guard) asserting the recorder received that exact reason, extending the existing TestEntryGuards cases at lines 127-169
- tests/test_ensemble_strategy.py: the outer except records reason='evaluation_error' and enter_long stays 0 (extends test_client_exception_fails_closed_and_does_not_raise, line 162)
- tests/test_ensemble_strategy.py: FAIL-SAFE — with a recorder that raises on every call, all 7 guard scenarios produce a dataframe identical to the same scenario with recording disabled, and nothing raises
- tests/test_ensemble_strategy.py: FAIL-SAFE ORDERING — an ordered mock asserts recorder.record is never called before enter_long has been assigned
- tests/test_ensemble_strategy.py: runmode='backtest' emits ZERO records; runmode='dry_run' emits one
- tests/test_ensemble_strategy.py: STRATEGY_VERSION is a 12-char hex string and appears in the recorded payload
- tests/test_prod_backup.py: verify_restore's min_tables is 6 and a restore missing decision_log fails the drill

### 3. R13-3: Exit and max-hold decisions

Completes the decision half of R13. populate_exit_trend (EnsembleSignalStrategy.py:182-201) records side='exit' with decision='exited'/reason='exit_signal' on a confident flat, decision='held'/reason='hold' otherwise, and reason='evaluation_error' from its except branch — in every case setting exit_long BEFORE calling the recorder. custom_exit (lines 203-215) records reason='max_hold' when the 5-day hold trips, and still returns the 'max_hold_5d' string freqtrade acts on. Entry and exit rows for the same pair and candle coexist because side is part of decision_uid. Same runmode gate as R13-2.

**Acceptance criteria**

- [ ] All 4 exit reasons (exit_signal, hold, max_hold, evaluation_error) are produced by at least one test and appear in decision_log
- [ ] A raising recorder cannot change exit_long or custom_exit's return value — the safe direction (toward flat) is never blocked by audit logging
- [ ] Every 1h candle in live/dry_run produces exactly 2 decision rows per pair (one entry, one exit), so the expected row rate is 4 pairs x 2 sides x 24 = 192/day
- [ ] custom_exit still returns the exact string freqtrade acts on; no change to exit behaviour
- [ ] All three CI jobs green

**Tests to write first**

- tests/test_ensemble_strategy.py: a confident flat records side='exit', decision='exited', reason='exit_signal' AND still sets exit_long=1 (extends test_exit_on_confident_flat_signal, line 172)
- tests/test_ensemble_strategy.py: a low-confidence flat records decision='held', reason='hold' (extends test_no_exit_on_low_confidence_flat, line 177)
- tests/test_ensemble_strategy.py: a long signal while in position records reason='hold'
- tests/test_ensemble_strategy.py: an exception in the exit path records reason='evaluation_error' and exit_long stays 0 (extends test_exit_does_not_raise_on_api_failure, line 186)
- tests/test_ensemble_strategy.py: custom_exit past max_hold records reason='max_hold' and still returns 'max_hold_5d' (extends test_max_hold_custom_exit_after_5_days, line 190)
- tests/test_ensemble_strategy.py: FAIL-SAFE — a raising recorder leaves exit_long and custom_exit's return value unchanged across all four exit scenarios
- tests/test_ensemble_strategy.py: FAIL-SAFE ORDERING — exit_long is assigned before recorder.record is called; custom_exit's return value is computed before the record call
- tests/test_ensemble_strategy.py: entry and exit rows for the same pair and candle both persist and are distinguished by side
- tests/test_ensemble_strategy.py: runmode='backtest' emits zero exit records

### 4. R13-4: Read API — GET /api/v1/decisions and GET /api/v1/decisions/coverage

The audit log becomes queryable over HTTP without SSH, and 'the log went dark' becomes a detectable state. GET /api/v1/decisions with filters pair, side, decision, reason, since_ms, until_ms; newest-first; keyset pagination on id; limit defaults to 100 and is capped at 500; every query carries both a LIMIT and an indexed predicate so this endpoint never repeats the unfiltered full-table scan at app/services/model_health.py:178. GET /api/v1/decisions/coverage returns, per pair: last_decision_at_ms, decisions_24h, expected_24h, coverage_ratio, entered_24h, skip-reason counts descending, unknown_reasons; plus a top-level receiving boolean. expected_24h is derived from wall-clock hours x sides (the timeframe is fixed at 1h, EnsembleSignalStrategy.py:51, and the universe is fixed at 4 pairs), NOT from klines — klines are stale from the Binance 451 block, and a coverage detector that goes blind exactly when data goes stale is worthless. receiving=false when the newest row is older than 2 candle intervals. Reads are unauthenticated behind the session-gated dashboard proxy, matching every other GET.

**Acceptance criteria**

- [ ] 'Why has the bot placed no trades this week' is answerable in ONE request: GET /api/v1/decisions/coverage returns per-pair skip-reason counts and the age of the last decision
- [ ] GET /api/v1/decisions never returns more than 500 rows and never issues a query without both a LIMIT and an indexed predicate
- [ ] Coverage reports receiving=false within 2 hours of freqtrade stopping, and does so correctly while klines are stale — the current production state must produce a truthful answer, not 'unknown'
- [ ] An empty result and an unavailable backend are distinguishable in the response (200 with an empty list vs 503 with a detail)
- [ ] All three CI jobs green

**Tests to write first**

- tests/test_decisions_endpoint.py: GET returns rows newest-first
- tests/test_decisions_endpoint.py: limit=2 returns 2 rows and a next_cursor; passing that cursor returns the next page with no overlap and no gap, including when rows are inserted mid-iteration
- tests/test_decisions_endpoint.py: limit=501 -> 422; limit omitted defaults to 100
- tests/test_decisions_endpoint.py: pair, side, decision and reason filters each exclude non-matching rows, independently and combined
- tests/test_decisions_endpoint.py: since_ms and until_ms bound decided_at_ms exactly as documented, verified at both boundaries
- tests/test_decisions_endpoint.py: GET on an empty table returns 200 with {"decisions": [], "next_cursor": null} — an empty audit log is a fact, not an error
- tests/test_decisions_endpoint.py: with 10k rows seeded, a limit=100 request materialises 100 rows, not the table (guards against the model_health.py:178 mistake)
- tests/test_decision_log.py: coverage_summary with 24 hourly entry rows for one pair reports decisions_24h=24 and coverage_ratio=1.0; with 12 rows, 0.5
- tests/test_decision_log.py: coverage_summary returns receiving=false when the newest row is older than 2 candle intervals and receiving=true at 90 minutes
- tests/test_decision_log.py: coverage_summary computes expected_24h WITHOUT reading klines — it returns the same value when the klines table is empty
- tests/test_decision_log.py: skip reasons are counted descending; a reason outside REASONS appears under unknown_reasons
- tests/test_decisions_endpoint.py: /coverage with get_health_engine returning None returns receiving=false with an explicit detail, never a 500

### 5. R13-5: Dashboard Decisions panel

Both stakeholders can answer 'why did the bot not trade' without a terminal. Adds frontend/src/lib/decision-log.ts (pure, unit-testable: reasonLabel, coverageStatus, summarizeSkips, plus fetchers alongside getSignal/getModelHealth in frontend/src/lib/trading-api.ts) and a DecisionLogPanel mounted in frontend/src/components/trading.tsx under the existing SignalFeed (line 755-757), wrapped in the file's existing PanelErrorBoundary (line 59) so a broken audit panel cannot take down positions or P&L. The panel shows: a coverage strip with three visually distinct states (recording, last decision N minutes ago / NOT recording, nothing since HH:MM / no decisions yet), a per-pair last-decision line, a 7-day skip breakdown sorted by count descending, and a filterable table of the last 100 decisions with the guard values behind each. Reason codes are rendered in plain, capability-first language with no technical jargon: stale_signal -> 'Forecast too old', volatility_guard -> 'Market too choppy', trend_guard -> 'Price below its trend line', no_signal -> 'No forecast available'. Reaches the API through the existing auth-gated proxy at /api/upstream/signal/api/v1/decisions... — no new proxy route is needed (frontend/src/app/api/upstream/signal/[...path]/route.ts).

**Acceptance criteria**

- [ ] One page load of the Trading tab shows the last 100 decisions with plain-language reasons, a 7-day skip breakdown per pair, and a coverage strip
- [ ] An empty decision log renders 'no decisions recorded' plus the age of the last decision (or 'never') — never an empty table that could be misread as 'nothing was skipped'
- [ ] 'Audit unavailable' is visually and structurally distinct from 'no decisions in this window'
- [ ] No reason code, enum value, or technical term leaks into user-facing text
- [ ] A thrown error in the panel is contained by PanelErrorBoundary and does not blank the Trading page
- [ ] npx tsc --noEmit, npm test and npm run build all pass (.github/workflows/ci.yml:86-98)

**Tests to write first**

- frontend/src/lib/decision-log.test.ts: reasonLabel returns a plain-English label for EVERY code in the vocabulary, iterating a hardcoded list — adding a backend reason without a label fails CI
- frontend/src/lib/decision-log.test.ts: no label contains a technical term from the code vocabulary (no raw slugs, no 'EMA50', no 'guard')
- frontend/src/lib/decision-log.test.ts: reasonLabel on an unknown code returns a readable fallback, never undefined and never the raw slug
- frontend/src/lib/decision-log.test.ts: coverageStatus maps receiving=false to 'not recording', a fresh row to 'recording', and a null last_decision_at to 'no decisions yet' — three distinct states
- frontend/src/lib/decision-log.test.ts: summarizeSkips groups a decision list into reason counts sorted descending, ties broken by label
- frontend/src/lib/decision-log.test.ts: a 503 from the audit API produces the 'unavailable' state, distinct from the empty state
- frontend/src/lib/decision-log.test.ts: rows with null signal_confidence or null ema50 render without throwing
- frontend/src/lib/trading-api.test.ts: getDecisions and getDecisionCoverage request the /api/upstream/signal/api/v1/decisions... paths, matching how getModelHealth is exercised

### 6. R13-6: Non-blocking recorder (conditional — build only when the trigger fires)

TRIGGER-GATED, not automatic. Build this only when one of two things is observed: candle-evaluation wall time is a measurable share of the loop, or /coverage shows decisions being missed. Today the trade loop already blocks up to 5.0s per pair per candle on SignalClient (user_data/strategies/signal_client.py:22,55), so a 1.0s POST is strictly less blocking than what the loop already accepts on a 1h timeframe — which is why this is last, not first. When triggered: DecisionRecorder gains a daemon worker thread fed by a bounded queue (maxsize 256, drop-oldest on overflow with a counted, logged drop) and a circuit breaker that stops attempting after 10 consecutive failures and probes again after 5 minutes. record() becomes a queue put returning in microseconds. Only after this slice is 'audit logging can never block a trade decision' literally true rather than bounded-at-1s.

**Acceptance criteria**

- [ ] record() returns in under 10ms regardless of transport behaviour, proven with a blocking fake
- [ ] Entry and exit signals are byte-identical to the synchronous recorder across every existing scenario
- [ ] Dropped records are counted, logged, and surfaced on /api/v1/decisions/coverage — lossiness is bounded, counted and visible, never silent
- [ ] The issue states the trigger explicitly and is closed as 'not needed yet' if the trigger has not fired
- [ ] All three CI jobs green

**Tests to write first**

- tests/test_decision_recorder.py: record() returns in under 10ms when the transport is stubbed to sleep 2s
- tests/test_decision_recorder.py: with the queue full, the oldest entry is dropped, a dropped counter increments, and record() still returns without blocking
- tests/test_decision_recorder.py: drops are logged so the gap is visible, never silent
- tests/test_decision_recorder.py: after 10 consecutive failures the breaker opens and no further HTTP is attempted; after the cooldown one probe runs and a success closes it
- tests/test_decision_recorder.py: the worker thread is a daemon, so a wedged worker cannot prevent freqtrade shutdown
- tests/test_decision_recorder.py: an exception inside the worker is logged and the worker survives it; nothing propagates to the caller
- tests/test_decision_recorder.py: flush(timeout) drains the queue within the deadline and is called on strategy shutdown
- tests/test_ensemble_strategy.py: every fail-safe and ordering assertion from R13-2 and R13-3 re-run green against the async recorder (behavioural equivalence)

### 7. R13-7: Signalled vs executed — confirm_trade_entry and reconciliation

Closes R13's third clause ('every order and fill', docs/PRD-trading-bot.md:125-126). Two parts. (a) confirm_trade_entry and confirm_trade_exit record a follow-up row carrying the freqtrade trade_id in the column reserved for it in R13-2, so 'the strategy signalled' and 'freqtrade actually acted' are distinguishable — with max_open_trades=3 (user_data/config.dry.json:16) against 4 pairs, plus the protections at EnsembleSignalStrategy.py:89-121 and pair locks, a signalled entry can be silently dropped today. (b) GET /api/v1/decisions/reconciliation joins decision='entered' rows against freqtrade's trade list (already proxied at app/api/v1/endpoints/trading.py:25-70) and reports two asymmetries: 'unexecuted' (an entry decision with no matching trade) and 'unexplained' (a trade with no matching entry decision — force-entry, manual intervention, the most alarming thing this system can surface). Also adds the freqtrade sqlite (user_data/tradesv3*.sqlite, docs/RUNBOOK.md:63-65) to the backup set, since the order half of R13 currently leans on a database nobody backs up.

**Acceptance criteria**

- [ ] For every trade the bot opens there is a decision_log row carrying its trade_id, and the chain signal-seen -> decision -> order is reconstructable from decision_log alone
- [ ] Entry decisions that never became trades are enumerated, so slot exhaustion and protection blocks stop being invisible
- [ ] Any trade with no corresponding decision is surfaced as 'unexplained' rather than dropped from the report
- [ ] A confirm_trade_entry audit failure can never change the boolean freqtrade acts on, proven by a test
- [ ] The freqtrade trade sqlite is inside the backup set and the restore drill asserts it
- [ ] R13 is only marked complete after this slice — not at R13-3 because the decision half looks done, and not at R13-5 because the dashboard looks finished
- [ ] All three CI jobs green

**Tests to write first**

- tests/test_ensemble_strategy.py: confirm_trade_entry records decision='entered' carrying trade_id and the same candle_time_ms as the signalling row
- tests/test_ensemble_strategy.py: confirm_trade_entry returning True is unaffected by a raising recorder — the audit call can never veto a trade
- tests/test_ensemble_strategy.py: confirm_trade_exit records the corresponding exit row with trade_id
- tests/test_decisions_endpoint.py: an entered decision matched by a freqtrade trade inside the candle window is reported 'matched'
- tests/test_decisions_endpoint.py: an entered decision with no trade in the window is reported under 'unexecuted' with its decision id and pair
- tests/test_decisions_endpoint.py: a trade with no entered decision is reported under 'unexplained' — this case must never be silently swallowed
- tests/test_decisions_endpoint.py: matching tolerates a configurable clock skew between decision and order timestamps, verified at both boundaries
- tests/test_decisions_endpoint.py: freqtrade unreachable -> 503 with a clear detail (matching the fail-closed contract at app/api/v1/endpoints/trading.py:33-38), never a partial reconciliation that looks complete
- tests/test_prod_backup.py: the backup set includes user_data/tradesv3*.sqlite
