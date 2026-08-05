# R7 — Freqtrade hosts execution: order lifecycle, partial fills, reconnection, position sizing, dry-run, backtesting, Telegram control

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

Backtesting — the one capability in R7 that is not available. The strategy calls the signal API for 'now' with no as-of parameter (user_data/strategies/signal_client.py:52-53 builds GET /api/v1/signal/{pair} with no time argument; the endpoint at app/api/v1/endpoints/signal.py:64-66 always scores the newest candle), so a freqtrade backtest would score every historical bar with today's signal. The code says so itself at user_data/strategies/EnsembleSignalStrategy.py:21-23 ('Historical backtests need a replay-capable signal source; until then use dry-run'). Consistent with that, user_data/data/binance/ is empty (no OHLCV ever downloaded) and no freqtrade backtest artifacts exist (user_data/backtest_results/ empty). The G0 gate was produced by a separate custom engine instead (scripts/run_backtest.py:3, app/backtest/engine.py:2, result docs/gates/G0-report.md), so freqtrade's own backtest/hyperopt path — including the DecimalParameter hyperopt spaces declared at EnsembleSignalStrategy.py:74-80 — has never been exercised. Second, smaller gap: docs/RUNBOOK.md:49 instructs putting live keys in `user_data/config.live.json`, but that file does not exist (user_data/ contains only config.dry.json), so the live execution path is undefined. Closing it: add an `as_of` (or candle-time) query parameter to the signal endpoint that scores against historical klines, pass it from SignalClient.get_signal (which already keys its cache by candle time, signal_client.py:41-50), run `freqtrade download-data`, and add a config.live.json that reads keys from env.

## Chosen approach

Design A — replay via a pure `candles_as_of` over a DB-loaded frame, with the caller owning the query

## Rationale

Both designs close the same gap the same way (as_of on the signal endpoint, SignalClient forwards the candle time it already caches by, an offline OHLCV path, a config.live.json). A wins on four concrete points.

1. Fit with existing patterns. A's core is `candles_as_of(frame, as_of, limit, interval_ms) -> DataFrame`: a pure function over an already-loaded frame plus scalars, with the endpoint owning the `load_klines` call. That is exactly the shape of app/services/market_data_status.py and backup_status.py. B instead widens the `CandleSource` Protocol (app/services/signal_service.py:43) with `get_candles_as_of` and implements it on BinanceRestCandleSource, DatabaseCandleSource and FallbackCandleSource. Three implementations, one of which (the Binance REST one) can never be exercised from this VPS and would be dead, untested code. More surface, less honesty.

2. Fail-safety. A states outright that replay reads only from the klines table. Historical bars must come from stored history; routing replay through the live/fallback source risks a live fetch quietly satisfying a historical request. B's fallback source makes that possible by construction.

3. Live-path leak. A gates as_of on `self.dp.runmode in (BACKTEST, HYPEROPT)` and asserts in a test that the dry-run/live call carries no as_of, so production keeps scoring the freshest candle. B leaves the live path implicit behind a "replay mode" constructor flag.

4. Scope discipline. B's slice 4 invents `live_config_status()` and wires it into the health surface — a readiness report about live trading that has never happened and cannot be verified behind the 451 block. That is reporting on work that does not exist; cut. A's slice 4 is just the file docs/RUNBOOK.md:49 already points at, keys via freqtrade's native FREQTRADE__EXCHANGE__* env override (same mechanism docker-compose.prod.yml already uses for Telegram), asserted well-formed and risk-identical to config.dry.json by the existing strategy CI job.

Grafted from B: reject future/out-of-range as_of at the boundary (both a lookahead guard and a bound on unauthenticated historical scoring work); a source-level assertion that no returned candle closes after as_of; a determinism test; an export/import round-trip test; and an explicit written decision on which backtester is authoritative for gates, since app/backtest/engine.py produced docs/gates/G0-report.md and freqtrade's engine will not agree with it.

Two facts that shape the slices and are not in either design: app/services/signal_service.py:28 sets INTERVAL="4h" while EnsembleSignalStrategy.timeframe is "1h", so the exporter must take the interval explicitly and slice 2's per-bar as_of will map 1h bars onto 4h scoring windows; and app/services/kline_store.load_klines returns the full pair history with a tz-aware `open_time` column and no close-time column, so the pure function must derive close time from an `interval_ms` scalar rather than assume one.

Ordering: slice 1 alone is shippable value (a replayable, auditable signal endpoint that works today with Binance blocked). Slice 2 makes freqtrade backtests score the right bar. Slice 3 makes them runnable offline. Slice 4 is the small documented-but-missing file.

## Grafted, and explicitly rejected

- From design B: reject a future as_of at validation with 422 rather than clamping it to now — this is both a lookahead guard and a bound on how much historical scoring work an unauthenticated caller can force the API to do.
- From design B: a source-level property assertion that no returned candle closes after as_of, in addition to the single mid-bar exclusion test.
- From design B: a determinism test — two identical as_of requests return identical direction, confidence and model_version.
- From design B: an export/import round-trip test proving the OHLCV export drops or reorders nothing.
- From design B: write down that the replayed window overlaps the ensemble's training data, so any freqtrade backtest over it is not out-of-sample and must not be reported as a gate-grade result.
- From design B: write down that the hyperopt spaces at EnsembleSignalStrategy.py:74-80 remain unexercised after slice 3, tracked as a known gap rather than implied complete.
- From design A's own risk list, promoted to an acceptance criterion of slice 3: state in docs which backtest engine (app/backtest/engine.py or freqtrade's) is authoritative for gates, since the two will disagree on fees, slippage and fills.
- Dropped from design B: live_config_status() and its wiring into the health surface. It is a readiness report about live trading that has never run and cannot be verified behind the 451 block — manufactured work. Slice 4's static assertions cover the real gap (the file simply does not exist).
- Dropped from design B: adding get_candles_as_of to the CandleSource Protocol and implementing it on all three sources. The BinanceRestCandleSource implementation would be permanently unexercisable from this VPS, and routing replay through FallbackCandleSource risks a live fetch quietly satisfying a historical request.
- Dropped from design B: the checked-in OHLCV fixture importer and the freqtrade backtest smoke test gated on freqtrade being importable. The exporter plus tmp_path tests give the same coverage without a second code path and a conditionally-skipped test that will read as green while proving nothing.

## Acceptance criteria

- [ ] Every slice is fully testable with fixture klines in SQLite: no live Binance, no exchange keys, no running freqtrade process. Any test that would need one is skipped explicitly with a stated reason, never silently passed.
- [ ] Tests are written first and observed failing for the right reason (missing function, missing param, missing file) before implementation.
- [ ] No new service, container, or third-party dependency is added by any slice.
- [ ] No slice reports a component as healthy, verified, or live-ready on the strength of configuration alone.
- [ ] Default behaviour is unchanged: a signal request with no as_of parameter produces the same response and the same prediction-log write as it does today.
- [ ] Each slice ships as one release via scripts/release.py and passes scripts/ci_gate.py before deploy.

## Delivery slices

### 1. Slice 1 — Replay-capable signal endpoint (?as_of=), database-only and excluded from the prediction log

GET /api/v1/signal/{pair}?as_of=<ISO8601 UTC> returns the signal that would have been produced at that instant. Three things change relative to today's behaviour, and only when as_of is present:

1. Candles come from the klines table via app/services/kline_store.load_klines, never from the injected CandleSource. Historical bars must come from stored history, and this is also why the slice is testable today with Binance returning HTTP 451.
2. record_prediction is skipped entirely. app/api/v1/endpoints/signal.py:69-86 currently logs every served signal with predicted_at_ms=now; replaying 2000 historical bars through that path would inject 2000 fabricated live predictions and silently corrupt R6 model-health accuracy. Suppression is part of this slice, not a follow-up.
3. The response's data_as_of reflects the replayed window, not wall clock, so any backtest artifact can be audited after the fact.

The core is a pure function `candles_as_of(frame, as_of, limit, interval_ms) -> pd.DataFrame` in app/services/signal_service.py, taking an already-loaded frame and scalars; the endpoint owns the load_klines query. It keeps only candles whose CLOSE (open_time + interval_ms) is at or before as_of — load_klines returns an open_time column only, so close time is derived from the interval_ms scalar. Slicing on open rather than close would let the model see the bar it is predicting; that is the single most important behaviour here.

Fail closed: fewer than CANDLE_LIMIT qualifying candles returns 503 naming the shortfall, never a padded or silently shortened window. A malformed or future as_of is rejected at validation (422), never clamped to now — that also bounds how much historical scoring work an unauthenticated caller can force. Without as_of, behaviour is byte-identical to today.

Fully testable now: no Binance, no keys, no freqtrade.

**Acceptance**

- [ ] `candles_as_of(frame, as_of, limit, interval_ms)` exists in app/services/signal_service.py, is pure (no engine, no session, no I/O), and is called by the endpoint with a frame the endpoint loaded itself.
- [ ] Filtering is on candle close (open_time + interval_ms <= as_of), and a test asserts a bar still open at as_of is excluded.
- [ ] With as_of present, candles are read only from the klines table; a test proves the injected CandleSource is never called.
- [ ] With as_of present, record_prediction is never called; a spy test asserts zero calls, and the same test asserts one call when as_of is absent.
- [ ] Insufficient history under as_of returns HTTP 503 with the shortfall in the message. No padding, extrapolation, or shortened window.
- [ ] Future or unparseable as_of returns HTTP 422.
- [ ] data_as_of in the response reflects the replayed window.
- [ ] A request without as_of is unchanged in response body and in prediction-log behaviour.
- [ ] All tests run in the existing backend CI job with fixture klines in SQLite; nothing in this slice needs Binance, keys, or freqtrade.

**Tests first**

- tests/test_signal_service.py::test_candles_as_of_excludes_candle_still_open_at_as_of — frame of 4h bars, as_of set mid-bar; the bar whose close is after as_of is absent from the result. This is the lookahead test and must fail before the function exists.
- tests/test_signal_service.py::test_candles_as_of_includes_candle_closing_exactly_at_as_of — boundary is inclusive on close, asserted explicitly rather than left to chance.
- tests/test_signal_service.py::test_candles_as_of_returns_at_most_limit_oldest_first — 500-row frame, limit=200: length is 200, ordering ascending, last row is the newest qualifying bar, index reset.
- tests/test_signal_service.py::test_candles_as_of_never_returns_a_candle_closing_after_as_of — property-style assertion over several as_of values that max(open_time + interval_ms) <= as_of always holds.
- tests/test_signal_service.py::test_candles_as_of_empty_when_as_of_precedes_all_history — returns an empty frame, does not raise.
- tests/test_signal_service.py::test_candles_as_of_accepts_naive_and_tz_aware_as_of_identically — guards a tz-comparison TypeError against the UTC-aware open_time column produced by load_klines.
- tests/test_signal_endpoint.py::test_as_of_scores_stored_candles_not_the_live_source — dependency-override a CandleSource that returns today's bars and would raise if called; the request succeeds, proving the live source was not consulted.
- tests/test_signal_endpoint.py::test_as_of_response_data_as_of_matches_replayed_window — data_as_of equals the last qualifying candle's close, not now.
- tests/test_signal_endpoint.py::test_as_of_request_does_not_record_prediction — spy on record_prediction: zero calls for the as_of request, exactly one for the same request without as_of.
- tests/test_signal_endpoint.py::test_as_of_returns_503_when_history_insufficient — fewer than CANDLE_LIMIT bars before as_of yields 503 whose message names the shortfall, not a degraded 200.
- tests/test_signal_endpoint.py::test_as_of_in_the_future_returns_422 — rejected, not clamped to now.
- tests/test_signal_endpoint.py::test_malformed_as_of_returns_422 — 'yesterday' and '2026-13-45' are rejected by validation.
- tests/test_signal_endpoint.py::test_as_of_is_deterministic — two identical as_of requests return identical direction, confidence and model_version.

### 2. Slice 2 — SignalClient forwards the candle time it already caches by; strategy passes it in backtest only

user_data/strategies/signal_client.py:41-50 keys its cache on (pair, candle_time) but `_fetch(pair)` at line 52 discards the candle time and requests the newest candle. Every cached entry for a given pair therefore holds the same 'now' signal under different keys — the exact bug that makes a freqtrade backtest score every historical bar with today's signal.

`_fetch(pair, as_of)` now appends ?as_of=<ISO8601 UTC> when as_of is not None and omits the parameter entirely when it is None, so the live URL stays byte-identical to today's. The fail-closed contract is unchanged: timeout, connection error, non-200, unparseable body all still return None, so a backtest run against a down API produces no entries rather than fabricated ones.

EnsembleSignalStrategy passes the bar's own timestamp only when self.dp.runmode is BACKTEST or HYPEROPT, and None in dry-run and live so production keeps scoring the freshest candle from the live source. A leak here would silently make live trading score stale database history; the test asserting as_of is None under dry-run is the guard.

Note a real mismatch this exposes: the strategy runs on a 1h timeframe while app/services/signal_service.py:28 sets INTERVAL='4h', so consecutive 1h bars will often resolve to the same 4h scoring window and return the same signal. That is correct, not a bug, but the SignalClient cache keys on the 1h candle time and will therefore issue up to four identical requests per 4h window. Acceptable; do not add a second cache layer in this slice.

Once this lands, the docstring caveat at EnsembleSignalStrategy.py:21-23 ('Historical backtests need a replay-capable signal source; until then use dry-run') is deleted, because it is no longer true.

Runs in the existing 'Strategy (freqtrade)' CI job against a fake requests session and a fake client. No freqtrade process, no exchange.

**Acceptance**

- [ ] SignalClient._fetch accepts an as_of argument, appends ?as_of=<ISO8601 UTC> when it is not None, and omits the parameter when it is None.
- [ ] SignalClient.get_signal passes its candle_time through to _fetch; the cache remains keyed on (pair, candle_time) and still guarantees at most one request per (pair, candle).
- [ ] The fail-closed contract is unchanged: no code path added in this slice can raise out of get_signal.
- [ ] EnsembleSignalStrategy passes as_of only when self.dp.runmode is BACKTEST or HYPEROPT; a test asserts as_of is None under DRY_RUN.
- [ ] The backtesting caveat at EnsembleSignalStrategy.py:21-23 is deleted in the same commit that makes it false, not before.
- [ ] All tests pass in the existing 'Strategy (freqtrade)' CI job without a running API, freqtrade process, or exchange.

**Tests first**

- tests/test_signal_client.py::test_fetch_includes_as_of_query_param_when_provided — fake session records the URL; as_of is present and is ISO8601 UTC.
- tests/test_signal_client.py::test_fetch_omits_as_of_when_none — the resulting URL is byte-identical to today's, proving the live path is unchanged.
- tests/test_signal_client.py::test_distinct_candle_times_produce_distinct_requests — two calls for the same pair at different candle times issue two HTTP requests with different as_of values. This is the bug being fixed; today both would be served one cached 'now' signal.
- tests/test_signal_client.py::test_repeat_call_for_same_candle_issues_no_second_request — the per-(pair, candle) cache still holds.
- tests/test_signal_client.py::test_as_of_request_failure_still_returns_none — 500 response, connection error, and unparseable body each yield None without raising.
- tests/test_ensemble_strategy.py::test_backtest_runmode_passes_bar_timestamp_as_of — fake client records (pair, as_of); populate_entry_trend over a 3-bar frame produces three distinct as_of values matching the bars.
- tests/test_ensemble_strategy.py::test_live_runmode_passes_no_as_of — under RunMode.DRY_RUN every call has as_of None.
- tests/test_ensemble_strategy.py::test_backtest_with_unreachable_signal_api_produces_no_entries — client returns None throughout; the enter_long column is all zeros, never NaN and never 1.

### 3. Slice 3 — Export stored klines to freqtrade OHLCV so a backtest runs with no exchange access

`freqtrade download-data` cannot run: Binance returns HTTP 451 from this VPS and user_data/data/binance/ is empty. Stated plainly: this slice cannot be closed with freshly downloaded Binance data, so it closes with the data we already own.

`python scripts/export_ohlcv.py --pair BTC/USDT --interval 1h` reads the klines table via app/services/kline_store.load_klines and writes user_data/data/binance/BTC_USDT-1h.json in freqtrade's OHLCV format (a list of [open_time_ms, open, high, low, close, volume]). The core is a pure function `klines_to_freqtrade_rows(frame) -> list[list]`; the script owns the query, the file write, and stdout — the same split as scripts/prod_backup.py and the pure-function-over-scalars convention.

Honesty requirements. The script prints the exported bar count and the actual first and last candle timestamps, so an operator cannot mistake a stale export for a current one; klines have ingested nothing since 2026-07-31, so any backtest produced from this is real but short and old. It exits non-zero and writes nothing when the pair has no rows — an empty file is worse than no file, because freqtrade would read it as a valid empty history.

With slices 1-3 in place, `freqtrade backtesting --strategy EnsembleSignalStrategy --timerange <exported range>` is runnable offline against the replay endpoint, exercising order lifecycle, partial fills and position sizing for real, and producing the first artifact under user_data/backtest_results/.

Two things this slice does NOT claim. It does not produce a gate-grade result: the ensemble was trained on the full kline history including the replayed window, so a backtest over that window is not out-of-sample. And the hyperopt spaces at EnsembleSignalStrategy.py:74-80 remain unexercised. Both are written into docs as known gaps rather than glossed over. This slice also records, in one line of docs, which backtester is authoritative for gates — app/backtest/engine.py produced docs/gates/G0-report.md and freqtrade's engine will not agree with it on fees, slippage or fill assumptions, and carrying two engines without a stated answer is how a wrong number gets shipped.

**Acceptance**

- [ ] scripts/export_ohlcv.py exists, takes --pair and --interval, and writes user_data/data/binance/<PAIR>-<interval>.json in freqtrade's OHLCV list format.
- [ ] `klines_to_freqtrade_rows(frame)` is pure: it takes a DataFrame and returns a list of lists, performing no query and no file I/O. The script owns the load_klines call and the write.
- [ ] Timestamps are integer epoch milliseconds and rows are ascending by time.
- [ ] An empty result exits non-zero and leaves no file on disk.
- [ ] The script prints bar count and the true first and last candle timestamps of what it exported.
- [ ] No new dependency: the script uses the existing SQLAlchemy engine, pandas, and stdlib json.
- [ ] A one-paragraph docs note records that (a) the exportable window ends 2026-07-31 because ingestion is down, (b) the replayed window overlaps model training data so results are not out-of-sample, (c) hyperopt remains unexercised, and (d) which of the two backtest engines is authoritative for gates.
- [ ] No claim anywhere in this slice's output or docs that R7 backtesting is complete or that a produced result is gate-grade.

**Tests first**

- tests/test_export_ohlcv.py::test_klines_to_freqtrade_rows_shape_and_types — six elements per row, timestamp an integer epoch-milliseconds value (not a Timestamp, not a float), OHLCV floats.
- tests/test_export_ohlcv.py::test_klines_to_freqtrade_rows_is_ascending_by_time — sorted output regardless of input row order, since freqtrade assumes ordering.
- tests/test_export_ohlcv.py::test_klines_to_freqtrade_rows_empty_frame_returns_empty_list — no crash, no header row.
- tests/test_export_ohlcv.py::test_round_trip_preserves_candles — exporting a frame and reading the JSON back yields the same timestamps and OHLCV values, so the export cannot silently drop or reorder bars.
- tests/test_export_ohlcv.py::test_export_writes_expected_filename_for_pair_and_interval — BTC/USDT + 1h resolves to BTC_USDT-1h.json under a tmp_path target dir.
- tests/test_export_ohlcv.py::test_export_exits_nonzero_and_writes_nothing_when_pair_has_no_klines — fail closed; assert the target file does not exist afterwards.
- tests/test_export_ohlcv.py::test_export_reports_actual_first_and_last_timestamps — stdout carries the real window and the real bar count.

### 4. Slice 4 — user_data/config.live.json with credentials from env, fail-closed when unset

docs/RUNBOOK.md:49 instructs the operator to put live keys in user_data/config.live.json, but that file does not exist — user_data/ contains only config.dry.json — so the live execution path is undefined.

Add config.live.json derived from config.dry.json with dry_run false, and exchange key/secret left as empty strings, supplied at runtime through freqtrade's native FREQTRADE__EXCHANGE__KEY / FREQTRADE__EXCHANGE__SECRET env overrides — the same mechanism docker-compose.prod.yml already uses for the Telegram credentials. No secrets in the repo, no new secret-management moving parts, no new dependency. Freqtrade already fails to start when the exchange rejects empty credentials, which is the fail-closed behaviour we want; we do not reimplement it.

Risk parameters (max_open_trades, tradable_balance_ratio, stake_amount, unfilledtimeout, order_types including stoploss_on_exchange) and the pair whitelist are asserted field-by-field identical to config.dry.json, so promoting to live cannot silently widen risk or trade a universe the ensemble was never validated on. docs/RUNBOOK.md is corrected to describe exporting env vars instead of editing a file with keys in it.

Verified by the existing 'Strategy (freqtrade)' CI job parsing the JSON. Stated plainly: this proves the live config is well-formed, risk-identical to dry-run, and free of embedded credentials. It cannot prove Binance accepts the keys from a geo-blocked VPS, and must not be reported anywhere as a verified live path.

**Acceptance**

- [ ] user_data/config.live.json exists, is valid JSON, and has dry_run false.
- [ ] exchange.key and exchange.secret are empty strings in the file; credentials are supplied only via FREQTRADE__EXCHANGE__KEY and FREQTRADE__EXCHANGE__SECRET env vars.
- [ ] A test greps the raw file for credential-shaped strings and fails the build if one is present.
- [ ] Risk parameters and pair whitelist are asserted equal to config.dry.json field by field.
- [ ] docs/RUNBOOK.md:49 is updated to describe exporting env vars, not editing a file containing keys.
- [ ] No new dependency, script, or secret-management component is introduced.
- [ ] Neither the code, the tests, nor the docs claim the live path is verified or that live trading is ready; the limitation (Binance returns 451 from this VPS, so credential validity is untested) is stated in the RUNBOOK.

**Tests first**

- tests/test_ensemble_strategy.py::TestLiveConfiguration::test_config_live_exists_and_is_valid_json — the file docs/RUNBOOK.md points at actually exists and parses.
- tests/test_ensemble_strategy.py::TestLiveConfiguration::test_config_live_contains_no_literal_credentials — exchange.key and exchange.secret are empty strings, and a regex over the raw file text finds no 40+ character base64-ish token. This fails the build if a key is ever committed.
- tests/test_ensemble_strategy.py::TestLiveConfiguration::test_config_live_risk_params_match_dry — max_open_trades, tradable_balance_ratio, stake_amount, unfilledtimeout and order_types compared field-by-field against config.dry.json.
- tests/test_ensemble_strategy.py::TestLiveConfiguration::test_config_live_has_dry_run_false_and_stoploss_on_exchange_true — the two flags that actually distinguish live, asserted explicitly.
- tests/test_ensemble_strategy.py::TestLiveConfiguration::test_config_live_pair_whitelist_matches_dry — the live universe cannot quietly differ from the validated one.
