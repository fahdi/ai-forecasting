# R8 — EnsembleSignalStrategy: hourly signal fetch, confidence + trend + volatility entry guards, four exit paths

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

The PRD's "threshold (tuned in backtesting)" clause is unmet, and structurally cannot be met today. The strategy only ever sets enter_long/exit_long on dataframe.iloc[-1] because the signal API serves the signal for "now" (acknowledged in the module docstring, user_data/strategies/EnsembleSignalStrategy.py:21-23), so a freqtrade backtest or hyperopt over history produces at most one signal-driven candle per run. Consequently buy_confidence_threshold=0.60 and volatility_ceiling=1.50 are untuned guesses: results/ is empty, there are no committed backtest or hyperopt artifacts anywhere in the repo, and the only "hyperopt" mentions are the two comments in the strategy file itself. Closing this needs a replay-capable signal source (generate historical signals per closed candle from stored klines, e.g. a batch/offline path through app/services/signal_service.generate_signal, or a recorded-signal parquet the SignalClient can read in backtest runmode), then an actual backtest/hyperopt run whose chosen thresholds are recorded. Also worth noting: the 1h decision loop consumes a 4h-horizon signal (app/services/signal_service.py:9-10), so the same signal is re-evaluated up to 4 times per horizon.

## Chosen approach

Design B (offline replay + sweep through the existing app/backtest engine), with three grafts from Design A and two of B's own slices cut as already-built.

## Rationale

Both designs agree on the only thing that matters: the blocker is that signals exist only for "now", so the first move is a pure per-candle replay function over caller-supplied klines. Slice 1 is effectively identical in both, so the decision turns on how the thresholds actually get chosen.

Design A chooses them by running freqtrade hyperopt. That requires a working freqtrade binary, a RecordedSignalClient wired into the live strategy path, and a change to populate_entry_trend so it annotates every candle rather than iloc[-1]. Freqtrade is down and Binance is geo-blocked, so that wiring cannot be verified end to end today, and A's slice 3 modifies the live decision path to serve a backtest need. That is the highest-risk, highest-operational-cost route to a number.

Design B chooses them with app/backtest/engine.simulate_long_flat, which already exists, is already tested (tests/test_backtest_engine.py), already models fees, slippage, stop-loss and max-hold, and is already the tool scripts/run_backtest.py uses. The guards it sweeps are user_data/strategies/decision.evaluate_entry, the exact pure function the live strategy already delegates to (EnsembleSignalStrategy._entry_allowed calls it). So the sweep exercises production guard code without touching production code, needs no freqtrade, no exchange and no keys, and every slice is fully testable offline. Reuse over rebuild, and fail-safety is preserved because nothing in the live path changes.

Two of B's own slices are cut as manufactured work. B slice 3's first half proposes extracting the entry guards into a pure function: /Users/isupercoder/Code/github/ai-forecasting/user_data/strategies/decision.py already does this (evaluate_entry at line 67, returning EntryDecision with a structured reason). B slice 4 proposes extracting exit attribution: evaluate_exit already exists at line 135, and the remaining exit paths (stoploss=-0.05, trailing, max_hold_5d in custom_exit) are freqtrade-side and unverifiable while freqtrade is down. Reporting an exit-path distribution from a simulator that does not model the trailing stop would be exactly the dishonest monitoring the house style forbids. Cut.

Grafted from A: (1) provenance columns (model_version, horizon, generated_at) on every replayed row plus a test that they come from signal_service constants, not literals; (2) the coverage sidecar that fails closed with a non-zero exit and no file rather than writing a thin parquet that would silently produce a meaningless sweep; (3) the provenance test that reads the committed artifact and asserts the two DecimalParameter defaults equal it, so code and evidence cannot drift.

One correctness constraint neither design caught, which reshapes slice 1: signal_service._is_stale (line 160) compares the last candle against pd.Timestamp.now(tz="UTC"), so a naive replay marks every historical signal stale and decision.evaluate_entry would reject all of them, producing zero trades and a fake "no signal survives" result. _is_stale already takes an injectable `now`, so replay must compute staleness as-of the candle being replayed. That is now an explicit test in slice 1.

Also deferred deliberately, not forgotten: the freqtrade-side RecordedSignalClient and per-candle annotation from A slice 3. It is real work, but it is what makes freqtrade backtests possible, not what closes the tuning gap, and it cannot be verified while freqtrade is down. It belongs in its own issue after freqtrade is back.

## Grafted, and explicitly rejected

- From A: carry model_version, horizon and generated_at on every replayed signal row, with a test asserting they are sourced from signal_service constants rather than literals, so any artifact can be attributed to a model version.
- From A: the recorder writes a coverage sidecar and fails closed (non-zero exit, no file written) when history is below the warmup threshold, instead of emitting a thin parquet that would silently produce a meaningless sweep.
- From A: a provenance test that parses the committed results/ artifact and asserts the strategy's two DecimalParameter defaults equal it, preventing silent drift between code and evidence.
- From A: an explicit test of the 4h-signal to 1h-candle forward-fill boundary (a signal applies to its own candle and the following 3 hourly candles, and is refused on the 5th).
- Dropped from B: the 'extract entry guards into a pure function' refactor (decision.evaluate_entry already exists and the strategy already delegates to it) and the whole exit-attribution slice (decision.evaluate_exit already exists; stop/trailing/max-hold live in freqtrade and cannot be honestly reported on while freqtrade is down).
- Dropped from A: freqtrade hyperopt, RecordedSignalClient and per-candle annotation inside the live strategy. Deferred to a separate issue once freqtrade runs again; they are not needed to close the tuning gap.

## Acceptance criteria

- [ ] The two DecimalParameter defaults in /Users/isupercoder/Code/github/ai-forecasting/user_data/strategies/EnsembleSignalStrategy.py (buy_confidence_threshold, volatility_ceiling) are set from a committed artifact under results/, and a test fails if code and artifact disagree.
- [ ] The artifact states the exact pair set, candle date range, bar count, trade count per fold and signal_service.MODEL_VERSION behind the chosen numbers, and says plainly if the window is too thin to be conclusive.
- [ ] Every slice's tests pass with no network access, no Binance, no exchange keys, no running freqtrade and no live signal API.
- [ ] No change is made to the live entry/exit decision path in EnsembleSignalStrategy or SignalClient in any of these slices; the existing tests/test_ensemble_strategy.py and tests/test_decision_evaluation.py suites stay green unedited.
- [ ] No new service, container, cron entry or third-party dependency is added; new code is one module under app/services/ plus two scripts under scripts/.
- [ ] Replayed signals contain no lookahead: the signal recorded for candle t is computed from candles up to and including t only.
- [ ] Staleness in replay is computed relative to the candle being replayed, not wall-clock now, so replayed signals are not uniformly stale.
- [ ] The threshold sweep evaluates the same guard code the live strategy runs (user_data/strategies/decision.evaluate_entry), not a reimplementation of it.

## Delivery slices

### 1. Slice 1: pure per-candle signal replay over a caller-supplied candle frame

Add /Users/isupercoder/Code/github/ai-forecasting/app/services/signal_replay.py exposing a single pure function:

    replay_signals(symbol: str, candles: pd.DataFrame, predictor=None) -> pd.DataFrame

It touches no database and no network. The caller owns the query, matching the convention in app/services/market_data_status.py and app/services/backup_status.py. For each index i from signal_service.WARMUP_BARS+1 to len(candles), it calls signal_service.generate_signal(symbol, candles.iloc[:i]) so the replayed signal is produced by exactly the production model and confidence formula, and emits one row per candle with columns: open_time, pair, direction, confidence, horizon, model_version, stale.

Two constraints that make this non-trivial and must be handled here, not downstream:

1. No lookahead. The call for candle t sees candles up to and including t and nothing after it.
2. As-of staleness. signal_service._is_stale (app/services/signal_service.py:160) compares the last candle to pd.Timestamp.now(tz="UTC"), so a naive replay marks every historical signal stale and every downstream guard evaluation would reject it, yielding a fake zero-trade result. _is_stale already accepts an injectable `now`; replay must recompute the stale field as-of the replayed candle's close (that is, stale is False for a contiguous history and True only where the preceding candle gap actually exceeds signal_service.STALE_AFTER). The Signal object returned by generate_signal is used for direction/confidence/model_version; its stale and generated_at fields are recomputed/recorded by replay rather than trusted.

Frames with WARMUP_BARS or fewer bars return an empty frame carrying the full column set rather than letting InsufficientDataError escape; the caller decides whether that is fatal.

Fully exercisable today with Binance geo-blocked, freqtrade down and no keys: the tests use synthetic frames only.

**Acceptance**

- [ ] app/services/signal_replay.py contains exactly one public function, performs no DB or network I/O, and imports no freqtrade module.
- [ ] Every test above passes offline with no live signal API, no exchange and no freqtrade installed.
- [ ] Replay is deterministic: two runs over the same frame produce identical rows.
- [ ] The stale column reflects candle-relative staleness; a fully contiguous historical frame produces no stale rows.
- [ ] InsufficientDataError never escapes replay_signals.

**Tests first**

- tests/test_signal_replay.py::test_emits_one_row_per_candle_after_warmup — synthetic 4h frame of WARMUP_BARS+10 bars yields exactly 10 rows with strictly increasing open_time
- tests/test_signal_replay.py::test_no_lookahead_call_prefixes — patch signal_service.generate_signal with a spy; assert every call receives a frame whose final open_time equals the emitted row's open_time and whose length equals the row's index position
- tests/test_signal_replay.py::test_row_equals_direct_generate_signal_on_same_prefix — for three sampled indices, replayed direction and confidence equal generate_signal(symbol, candles.iloc[:i]) exactly
- tests/test_signal_replay.py::test_mutating_later_candles_does_not_change_earlier_rows — replay a frame, mutate closes after index k, replay again, assert rows up to k are identical
- tests/test_signal_replay.py::test_stale_is_computed_as_of_the_replayed_candle_not_wall_clock — a contiguous historical frame ending years in the past yields stale=False on every row (this test fails against a naive implementation that inherits generate_signal's wall-clock stale flag)
- tests/test_signal_replay.py::test_stale_is_true_across_a_real_history_gap — a frame with a gap larger than signal_service.STALE_AFTER marks the row after the gap stale=True
- tests/test_signal_replay.py::test_frame_shorter_than_warmup_returns_empty_typed_frame — 10-bar frame returns zero rows with the full column set and raises nothing
- tests/test_signal_replay.py::test_model_version_and_horizon_sourced_from_signal_service — asserts equality with signal_service.MODEL_VERSION and signal_service.INTERVAL, not string literals

### 2. Slice 2: record replayed signals to parquet from stored klines, failing closed on thin history

Add /Users/isupercoder/Code/github/ai-forecasting/scripts/generate_replay_signals.py, shaped like scripts/backfill_klines.py: a testable core plus a thin argparse main.

    build_replay(engine, symbol: str, interval: str, out_dir: Path) -> dict

It loads candles via app.services.kline_store.load_klines(engine, pair, interval), calls replay_signals, and writes results/replay_signals_{SYMBOL}_{interval}.parquet plus a JSON sidecar recording: symbol, interval, first and last candle open_time, bar count, replayed row count, stale row count, and signal_service.MODEL_VERSION. main() iterates signal_service.UNIVERSE by default and prints the coverage table.

Fail-closed and honest monitoring are the point of this slice. If the DB holds fewer than WARMUP_BARS+1 bars for a symbol, or the pair is unknown, it writes nothing for that symbol, says so explicitly, and exits non-zero. It must never emit a thin parquet that would silently produce a meaningless sweep in slice 3, and it must never report a symbol as covered when it is not.

Valuable on its own even if slice 3 never lands: it is the first committed evidence of what the model would have emitted over history, and its coverage report is the honest answer to whether the klines already in Postgres (stale since 2026-07-31) are sufficient to tune anything at all. Runs entirely against the existing database; no exchange, no keys, no freqtrade.

**Acceptance**

- [ ] Running the script against the production database prints a per-symbol coverage table with real first/last candle dates and bar counts, and exits non-zero if any universe symbol is below warmup.
- [ ] No parquet is ever written for a symbol that failed the coverage check.
- [ ] The script requires no exchange access, no API keys and no running signal API; it reads klines only.
- [ ] Sidecar JSON is committed alongside the parquet so any later number is traceable to a date range and a model version.
- [ ] Argparse main is a thin wrapper; all logic under test lives in build_replay.

**Tests first**

- tests/test_generate_replay_signals.py::test_writes_parquet_that_round_trips_to_replay_output — in-memory sqlite engine seeded with synthetic klines; the written file reads back equal to replay_signals on the same frame
- tests/test_generate_replay_signals.py::test_sidecar_reports_actual_coverage — first/last open_time, bar count and row count in the sidecar match the seeded data exactly
- tests/test_generate_replay_signals.py::test_sidecar_records_model_version_from_signal_service
- tests/test_generate_replay_signals.py::test_insufficient_history_writes_nothing_and_returns_nonzero — engine seeded with 10 bars produces no parquet, no sidecar, and a non-zero exit code
- tests/test_generate_replay_signals.py::test_unknown_symbol_returns_nonzero_without_writing
- tests/test_generate_replay_signals.py::test_partial_universe_failure_is_reported_not_swallowed — one covered symbol and one thin symbol yields a non-zero exit and a report naming the thin symbol

### 3. Slice 3: sweep the two entry-guard thresholds through the existing backtest engine and bind the defaults to the committed artifact

Add /Users/isupercoder/Code/github/ai-forecasting/scripts/tune_entry_guards.py. This is the slice that actually closes the PRD's "threshold (tuned in backtesting)" clause.

It loads the 1h klines for a pair, computes ema50 and 20-bar annualized volatility, joins the 4h replayed signals from slice 2 forward-filled onto the 1h candles (a signal covers its own candle and the following three 1h candles, and is refused beyond that: this is the 1h-decision / 4h-horizon reuse the live system already does, made explicit), and for each cell of a grid of buy_confidence_threshold x volatility_ceiling values calls user_data.strategies.decision.evaluate_entry per candle — the exact pure function EnsembleSignalStrategy._entry_allowed already delegates to, so the sweep evaluates production guard code rather than a reimplementation.

The resulting 1/0 entry-intent series is fed to app.backtest.engine.simulate_long_flat with threshold=0.5 and the same fee and slippage constants scripts/run_backtest.py uses, plus stop_loss=0.05 and max_hold_bars=120 (5 days of 1h bars) to match the strategy's stop and max hold. Evaluation is per walk-forward fold using the existing app.models.ensemble_trainer.walk_forward_splits helper, reporting Sharpe, max drawdown and trade count per fold and per cell, not one aggregate number.

Output is committed under results/: a params JSON with the chosen buy_confidence_threshold and volatility_ceiling, plus results/R8-threshold-tuning.md recording pair set, candle date range, bar count, per-fold trade counts, model_version and the selection rule. The two DecimalParameter defaults in user_data/strategies/EnsembleSignalStrategy.py move to the chosen values, with the comment pointing at the artifact instead of the word "hyperopt", and a provenance test asserts code equals artifact.

Honest-monitoring requirement, non-negotiable: the simulator does not model the trailing stop, and the klines end 2026-07-31. If folds disagree on the winning cell, or a fold produces too few trades to mean anything, the markdown says so and the defaults stay at 0.60/1.50 with the artifact recording the null result. The slice still ships: the sweep, the artifact and the provenance binding are the deliverable, not a particular pair of numbers. Nothing here requires Binance, exchange keys, a running signal API or freqtrade.

**Acceptance**

- [ ] results/ contains a params JSON and R8-threshold-tuning.md, both committed, both naming the pair set, candle date range, bar count, per-fold trade counts and model_version.
- [ ] The strategy's two DecimalParameter defaults equal the artifact, enforced by a test that fails on drift.
- [ ] The sweep calls decision.evaluate_entry directly; there is no second copy of the guard logic anywhere in the repo.
- [ ] The markdown explicitly states the two known limitations: the simulator does not model the trailing stop, and the data window ends 2026-07-31, so the numbers are honest only about that window.
- [ ] If folds disagree or trade counts are too low, the artifact says inconclusive, the defaults remain 0.60/1.50, and the slice still ships the provenance mechanism.
- [ ] No change to EnsembleSignalStrategy beyond the two default values and their comment; the existing tests/test_ensemble_strategy.py and tests/test_decision_evaluation.py suites remain green unedited.
- [ ] The whole slice runs with no exchange access, no keys and no freqtrade binary.

**Tests first**

- tests/test_tune_entry_guards.py::test_signal_forward_fill_covers_own_candle_and_next_three_hours — the 4th following 1h candle still sees the signal, the 5th sees None
- tests/test_tune_entry_guards.py::test_candles_with_no_covering_signal_produce_no_entry — a gap in the recorded signals yields zero entry intent, never a permissive default
- tests/test_tune_entry_guards.py::test_indicator_parity_with_strategy — ema50 and volatility_ann computed by the sweep equal EnsembleSignalStrategy.populate_indicators output on the same frame (guards against the sweep tuning against different indicator values than the strategy runs on)
- tests/test_tune_entry_guards.py::test_sweep_returns_one_row_per_grid_cell_per_fold
- tests/test_tune_entry_guards.py::test_raising_confidence_threshold_never_increases_trade_count — monotonicity check that catches a misaligned join
- tests/test_tune_entry_guards.py::test_raising_volatility_ceiling_never_decreases_trade_count
- tests/test_tune_entry_guards.py::test_sweep_is_deterministic_for_fixed_input
- tests/test_tune_entry_guards.py::test_artifact_records_date_range_bar_count_trade_counts_and_model_version — every field present and non-empty
- tests/test_tune_entry_guards.py::test_disagreeing_folds_produce_a_null_result_artifact_not_a_pick — synthetic per-fold results with different winners yield an artifact flagged inconclusive and no default change
- tests/test_ensemble_strategy.py::test_thresholds_match_committed_tuning_artifact — parses the results/ params JSON and asserts buy_confidence_threshold.value and volatility_ceiling.value equal it
- tests/test_ensemble_strategy.py::test_tuning_artifact_model_version_matches_signal_service — guards against inheriting thresholds tuned under a different model version
