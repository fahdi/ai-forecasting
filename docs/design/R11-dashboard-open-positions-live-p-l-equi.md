# R11 — Dashboard: open positions + live P&L, equity curve vs BTC buy-and-hold, signal feed with reasoning, model-health panel, system status

Status: designed, not yet implemented. Design council of two independent
designs judged head to head.

## Gap being closed

No real equity time series and no BTC buy-and-hold benchmark. Needs (a) a series source — freqtrade /api/v1/daily or a periodic balance snapshot table — and (b) a benchmark series from the existing klines table (BTCUSDT closes, normalized to the same start), then a two-line chart replacing the two-point placeholder. Also: model_votes unrendered. No CI test touches any Trading panel — the frontend job (.github/workflows/ci.yml:67-98) runs tsc, vitest and next build, but the only vitest files are frontend/src/lib/{forecast-rows,security-headers,session,system-status}.test.ts (28 assertions total, all pure lib functions); system-status.test.ts covers the dashboard header helper (frontend/src/components/dashboard.tsx:119), not trading.tsx:636 SystemStatus. @testing-library/react is not in frontend/package.json, so component tests need a new dev dependency.

## Chosen approach

Design A (pure scalar functions + one read-only route per series + vitest-only frontend libs), with Design B's fail-closed HTTP contract, overlap-clipping/renormalisation semantics, and its explicit rejection of degenerate inputs grafted in.

## Rationale

Both designs converge on the same four slices and the same source of truth (stored BTCUSDT klines for the benchmark, freqtrade /api/v1/daily for equity, no new table, no cron, no new service). The deciding difference is the frontend dependency. Design B adds @testing-library/react + jsdom in slice 4 and calls it unavoidable; it is not. `frontend/package.json` already has vitest and recharts, the four existing test files are all pure lib modules, and both designs already extract the load-bearing logic (alignment, vote summarisation) into pure lib functions that vitest covers today. Adding a test runtime and a jsdom vitest environment to assert on JSX wiring that both designs deliberately keep trivially thin is manufactured work. Design A wins on "no new dependencies unless genuinely unavoidable" and ships slice 4 faster.

Design B is better on two points, and those are grafted. First, its HTTP contract: `app/api/v1/endpoints/trading.py:33-60` already establishes 503-unreachable / 502-misbehaving on this exact router, and the frontend already renders "Execution engine offline" for it (trading.tsx:340-347). Design A's 200-with-status-unavailable invents a second, competing convention on the same router for the same failure. Second, its alignment semantics are stricter: clip both series to their overlapping range and re-base *after* clipping, so both lines genuinely start at 1.0 on a shared date. Design A's forward-fill-and-merge would draw a benchmark line that starts months before the strategy line and visually exaggerates the strategy's relative performance. Design B's explicit "fewer than two points is not a curve" rule is also the exact regression guard for the two-point placeholder being deleted at trading.tsx:417-431, so it is kept.

Slice 1 delivers value on day one with Binance blocked and freqtrade down: it is the first buy-and-hold reference the system has ever had, computed entirely from klines already on disk, and it makes the 2026-07-31 cut-off a first-class part of the payload rather than a silent truncation. Slice 4 is fully independent of 1-3 and could be shipped in any order; it is placed last only because the equity gap is the stated R11 gap.

Cut from both designs: the model-health panel and system-status items in the R11 heading (they already exist and neither design proposes work there), Design B's component-test slice and its devDependency, and any notion of a balance-snapshot table or ingestion cron. Nothing here reports on work that does not exist yet.

## Grafted, and explicitly rejected

- From B: keep the existing router's fail-closed HTTP contract (503 unreachable / 502 misbehaving) for the equity endpoint instead of A's 200-with-status-unavailable, so `app/api/v1/endpoints/trading.py` has one convention, not two. A's status vocabulary is retained inside the pure function for data verdicts, which is where it belongs.
- From B: clip both series to their overlapping range and re-base *after* clipping, rather than A's forward-fill-and-merge. A's merge would start the benchmark line months before the strategy line on a shared axis and visually inflate relative strategy performance.
- From B: the 'fewer than two points is not a curve' rule, kept as an explicit named test in both the backend benchmark function and the frontend aligner, since it is the precise regression guard for the two-point placeholder being deleted at trading.tsx:417-431.
- From B: reject zero/negative first close and zero/negative starting balance with an explicit 'invalid' verdict rather than dividing.
- From B: return 502 when the /api/v1/daily starting-balance field is absent rather than assuming a default, and state in the release note that the live payload shape is unverified until freqtrade next runs.
- From B: drive the panel's 'no equity series' prose from the returned note/status rather than leaving it hardcoded.
- From A (kept over B): no @testing-library/react, no jsdom, no vitest environment change. B's component-test slice and its devDependency are cut; the pure-lib extraction both designs already perform makes it unnecessary.
- From A (kept over B): a single `mode`-driven consumer in trading.tsx with all branching decided in the pure module, which is what makes the untested JSX acceptable.
- Cut from both: the model-health panel and system-status items named in the R11 heading. They already exist and neither design proposed work on them.

## Acceptance criteria

- [ ] No new service, container, table, migration, cron job or runtime dependency is added by any slice. `frontend/package.json` dependencies and devDependencies are byte-identical before and after R11.
- [ ] Every slice is written test-first: the named tests are committed and observed failing for the right reason (assertion failure or ImportError/ModuleNotFoundError on the not-yet-written module), never failing on a typo or a wrong import path, before any implementation lands.
- [ ] Every slice is fully verifiable on this VPS today, with Binance returning HTTP 451, no live keys, and no freqtrade process running. No test in any slice requires network access.
- [ ] New backend logic lives in pure functions in `app/services/` that take already-fetched scalars/rows and return a dict verdict, with the caller owning the SQL and the HTTP call, matching `app/services/market_data_status.py` and `app/services/backup_status.py`. No `app/services/` module added by R11 imports httpx, sqlalchemy or the DB engine.
- [ ] Nothing in the dashboard renders a line, a number or a label that was not measured. Absent data renders as a named absence (which series, why, as-of when); it never renders as 0, as a flat line, or as an interpolated segment.
- [ ] The stale-since-2026-07-31 kline cut-off is visible in the UI wherever the benchmark is drawn. The benchmark line never extends past the newest stored kline.
- [ ] New endpoints on the trading router keep the existing fail-closed contract from `app/api/v1/endpoints/trading.py:33-60`: 503 when freqtrade is unreachable, 502 when it answers with an unexpected status or payload shape. A truthful verdict about the data (stale, insufficient) is HTTP 200; a broken dependency is not.
- [ ] The three existing CI jobs (backend, frontend, freqtrade strategy) stay green with no config change. The frontend job picks up the new `*.test.ts` files automatically under the existing `vitest run`.
- [ ] The two-point placeholder at `frontend/src/components/trading.tsx:417-431` and its `first_trade_timestamp`/`latest_trade_timestamp` chartData construction are deleted by the end of slice 3, not left behind a flag.
- [ ] `scripts/release.py` cuts exactly one release per slice, and `scripts/ci_gate.py` passes on the released commit.

## Delivery slices

### 1. Slice 1: BTC buy-and-hold benchmark as a pure function over stored klines

The system has never had a benchmark to judge strategy performance against. Add `app/services/benchmark_series.py` exposing `buy_and_hold_series(closes, start_ms=None, end_ms=None, now=None)`, a pure function in the style of `app/services/market_data_status.py`: the caller passes an already-fetched list of `(open_time_ms, close)` tuples, the function judges the data and returns a verdict dict.

Return shape: `{'status', 'message', 'points': [{'t': open_time_ms, 'value': float}], 'first_close', 'newest_point_ms'}`. `value` is the close divided by the first close *inside the requested window*, so the series plots as a growth multiple starting at 1.0 and is directly comparable to the strategy equity series from slice 2.

Statuses: `'ok'`; `'insufficient'` when fewer than two points fall in the window, with the count named in the message and `points` empty (a one-point curve is never emitted; that is exactly the failure mode of the placeholder slice 3 deletes); `'truncated'` when the newest in-window point is more than 2.5 intervals older than `end_ms`, message stating the gap in hours, reusing the staleness reasoning of `market_data_status.py`; `'invalid'` when the first close is zero or negative, so there is no division by zero and no silently infinite multiple. The function never extrapolates past the newest kline.

The caller is a new `GET /api/v1/trading/benchmark` handler on the existing router in `app/api/v1/endpoints/trading.py`, which builds the closes list from `app/services/kline_store.py::load_klines(engine, 'BTCUSDT', '4h')` (it returns a DataFrame; the handler converts, the service function stays free of pandas and SQLAlchemy) and returns the verdict verbatim with HTTP 200. It does not touch freqtrade and has no auth dependency on it.

Valuable and fully testable today: BTCUSDT 4h klines are already persisted, so this ships a real buy-and-hold return curve with Binance geo-blocked, no keys, and freqtrade down. In production right now it will return status `'truncated'` with the 2026-07-31 cut-off stated, which is the correct and useful answer.

**Acceptance**

- [ ] `app/services/benchmark_series.py` imports nothing from httpx, sqlalchemy, or the app DB layer. Its only non-stdlib import may be for typing.
- [ ] All eleven tests above are committed failing first (ImportError on the missing module / 404 on the missing route), then pass.
- [ ] The endpoint returns HTTP 200 for every data verdict including 'truncated', 'insufficient' and 'invalid'. It returns 5xx only if the DB itself is unreachable.
- [ ] No point in the returned series has a timestamp later than the newest stored kline, under any start_ms/end_ms combination.
- [ ] The whole slice passes with no network access and no freqtrade running.
- [ ] One release cut via `scripts/release.py`; `scripts/ci_gate.py` green on that commit.

**Tests first**

- tests/test_benchmark_series.py::test_normalises_first_close_to_one — closes [(0,100),(1,130)] yields points [1.0, 1.3] and status 'ok'
- tests/test_benchmark_series.py::test_window_normalises_to_first_close_inside_window — five closes, start_ms/end_ms selecting the middle three; the first in-window point is 1.0, not the global first close
- tests/test_benchmark_series.py::test_single_point_in_window_is_insufficient — status 'insufficient', points empty, message names the count
- tests/test_benchmark_series.py::test_empty_closes_is_insufficient_not_an_exception
- tests/test_benchmark_series.py::test_newest_point_far_before_end_ms_is_truncated — end_ms is 'now', newest close is five days earlier; status 'truncated' and the message states the gap in hours
- tests/test_benchmark_series.py::test_newest_point_within_threshold_of_end_ms_is_ok — one interval of lag does not read as truncated
- tests/test_benchmark_series.py::test_zero_or_negative_first_close_is_invalid — status 'invalid', points empty, no ZeroDivisionError
- tests/test_benchmark_series.py::test_points_are_sorted_by_time_when_input_is_unordered
- tests/test_trading_benchmark_endpoint.py::test_returns_points_from_seeded_btcusdt_klines — seeded store, HTTP 200, points match the pure function's output
- tests/test_trading_benchmark_endpoint.py::test_stale_klines_return_http_200_with_status_truncated — a truthful verdict is not a server error
- tests/test_trading_benchmark_endpoint.py::test_no_klines_for_pair_returns_http_200_with_status_insufficient

### 2. Slice 2: strategy equity series from freqtrade /api/v1/daily, fail-closed

There is no measured equity time series anywhere in the system. Add `app/services/equity_series.py` exposing pure `equity_series(daily_rows, starting_balance)`, which turns freqtrade's per-day rows into a cumulative growth multiple on the same 1.0 base as slice 1, so the two series share an axis.

Return shape: `{'status', 'message', 'points': [{'t': day_ms, 'value': float}], 'first_day', 'last_day'}`. Statuses: `'ok'`; `'insufficient'` for fewer than two days; `'unavailable'` when `daily_rows` is empty — points empty, never a flat 1.0 line, because a flat line reads as a measured break-even rather than as no data; `'invalid'` when `starting_balance` is zero or negative. Rows are sorted by day and de-duplicated (last write wins) so the time axis is monotonic regardless of input order. Days with no trades are carried at the previous value; the function never interpolates *between* days, because /api/v1/daily is day-granular and inventing intraday points would fabricate drawdown detail that was not measured.

Add `GET /api/v1/trading/equity` to the existing router in `app/api/v1/endpoints/trading.py`, reusing the `get_freqtrade_client` dependency and the exact token-login flow and fail-closed contract already at lines 33-60: 503 when freqtrade is unreachable or login raises, 502 when login or /api/v1/daily returns a non-200 or a payload missing the expected keys. It passes `starting_balance` from the /api/v1/daily response's own starting-balance field where present, and returns 502 rather than guessing when it is absent. It never falls back to profit.first_trade_timestamp/latest_trade_timestamp — that is the fabrication slice 3 deletes.

Honest note on today's reality: freqtrade is DOWN behind the HTTP 451 geo-block, so in production this endpoint will return 503 with a detail naming freqtrade. That is the correct shipped behaviour and it is fully testable now with a stubbed client via FastAPI `dependency_overrides`, the pattern the existing trading endpoint tests already use. What cannot be verified until the bot runs is the exact field naming of the live /api/v1/daily payload; the endpoint is coded against freqtrade's documented schema and treats any deviation as 502, so an unverified shape degrades into a visible failure rather than a silently empty curve. This must be re-verified the first time freqtrade starts, and the release note for this slice must say so.

**Acceptance**

- [ ] `app/services/equity_series.py` imports nothing from httpx, fastapi or the DB layer.
- [ ] All twelve tests committed failing first, then passing.
- [ ] The endpoint's failure contract is identical to the existing `trading_summary` at `app/api/v1/endpoints/trading.py:33-60`: 503 unreachable, 502 misbehaving. No new convention is introduced on this router.
- [ ] A reachable bot with zero trades is HTTP 200 with status 'unavailable' and zero points — distinguishable in the response from an unreachable bot, which is 503.
- [ ] No code path emits a point whose value was not derived from a freqtrade-reported day.
- [ ] The release note for this slice states explicitly that the live /api/v1/daily payload shape is unverified against this deployment and must be re-checked the first time freqtrade starts.
- [ ] The whole slice passes with no network access and no freqtrade running.
- [ ] One release cut via `scripts/release.py`; `scripts/ci_gate.py` green.

**Tests first**

- tests/test_equity_series.py::test_cumulates_daily_profit_into_growth_multiple — starting_balance 1000, days [+50,-20,+30] yields [1.05, 1.03, 1.06]
- tests/test_equity_series.py::test_rows_are_sorted_and_deduped — out-of-order and duplicate days produce a strictly increasing time axis with one point per day
- tests/test_equity_series.py::test_day_with_no_trades_carries_previous_value_and_is_not_interpolated
- tests/test_equity_series.py::test_empty_rows_is_unavailable_with_no_points — must not emit a flat 1.0 line
- tests/test_equity_series.py::test_single_day_is_insufficient
- tests/test_equity_series.py::test_zero_or_negative_starting_balance_is_invalid_with_no_division
- tests/test_trading_equity_endpoint.py::test_returns_503_when_freqtrade_unreachable — stub client raises httpx.HTTPError; assert 503 and that the detail names freqtrade (today's production path)
- tests/test_trading_equity_endpoint.py::test_returns_502_when_login_is_rejected
- tests/test_trading_equity_endpoint.py::test_returns_502_when_daily_payload_is_missing_expected_keys — 200 response, wrong shape, assert 502 not an empty series
- tests/test_trading_equity_endpoint.py::test_returns_502_when_starting_balance_is_absent_rather_than_assuming_one
- tests/test_trading_equity_endpoint.py::test_returns_points_on_happy_path — stub returns three daily rows; assert three points and status 'ok'
- tests/test_trading_equity_endpoint.py::test_bot_reachable_with_zero_trades_returns_http_200_status_unavailable

### 3. Slice 3: aligned two-line equity-vs-BTC chart replacing the two-point placeholder

`frontend/src/components/trading.tsx:417-431` currently builds a two-point chart from `profit.first_trade_timestamp` and `profit.latest_trade_timestamp` and draws a straight line between 0 and total closed profit. That is a fabricated equity curve. Delete it.

Add `frontend/src/lib/equity-chart.ts` (pure, vitest-only, matching the existing `frontend/src/lib/*.test.ts` convention — no new dependency, no jsdom, no component test). Export `alignSeries(equity, benchmark)` returning `{mode, rows, note}` where `mode` is `'both' | 'benchmark-only' | 'equity-only' | 'none'`.

Alignment rules, which are the whole point of the module: clip both series to their overlapping time range, then re-base each clipped series to its own first in-range value so both lines genuinely start at 1.0 on the same date. Re-basing happens after clipping, never before — otherwise the benchmark carries months of head start and visually inflates the strategy. Rows are keyed on UTC date. A series is carried forward only within its own range and is null after its last point, so neither line is drawn past the data. Fewer than two aligned rows yields mode `'none'`; non-overlapping ranges yield mode `'none'` rather than two unrelated lines on one axis. `note` is a human-readable string naming what is missing or truncated and as of when, for example `BTC benchmark ends 2026-07-31 (market data feed down)` or `No equity series: execution engine unreachable`.

Add typed `getEquityCurve()` and `getBenchmarkCurve()` fetchers to `frontend/src/lib/trading-api.ts` against the two slice 1 and 2 endpoints. `getEquityCurve()` maps a 503/502 to an `unavailable` result carrying the server's detail rather than throwing.

Rewire `EquityPanel` in `frontend/src/components/trading.tsx:348-496` to fetch both, feed `alignSeries`, and render a two-line recharts `LineChart` (strategy vs BTC buy-and-hold) plus the `note` text. The KPI grid above it is unchanged. The existing hardcoded prose about no equity series is replaced by the returned `note`, so the message is driven by measured state instead of being baked in. All decision logic lives in `equity-chart.ts`; the JSX is a thin consumer with no branching beyond `mode`.

What ships in production today: mode `'benchmark-only'` — a real BTC buy-and-hold curve from stored klines, ending 2026-07-31 and saying so, next to an accurate statement that no strategy equity was measured because the execution engine is unreachable. That is strictly more honest than what is on screen now. Slice 3 depends on slice 1; it degrades correctly without slice 2.

**Acceptance**

- [ ] `frontend/package.json` is unchanged. No @testing-library/react, no jsdom, no vitest environment config. The new tests run under the existing `vitest run` in the existing frontend CI job (.github/workflows/ci.yml:67-98).
- [ ] All eight tests committed failing first, then passing.
- [ ] `profit.first_trade_timestamp`/`profit.latest_trade_timestamp` no longer appear anywhere in the chart data path in `frontend/src/components/trading.tsx`; grep confirms the placeholder block at 417-431 is gone.
- [ ] Every branch shown to the user (`'both'`, `'benchmark-only'`, `'equity-only'`, `'none'`) is decided inside `alignSeries` and covered by a test. `trading.tsx` contains no alignment, re-basing, clipping or note-composition logic.
- [ ] Neither rendered line extends past its own last measured point.
- [ ] `tsc` and `next build` pass; the frontend CI job is green.
- [ ] One release cut via `scripts/release.py`; `scripts/ci_gate.py` green.

**Tests first**

- frontend/src/lib/equity-chart.test.ts::clips both series to their overlapping range — equity days 3-7, benchmark days 1-10; rows cover 3-7 only
- frontend/src/lib/equity-chart.test.ts::re-bases after clipping so both series start at 1.0 on the first shared day — benchmark is re-based to its day-3 value, not left on its day-1 base
- frontend/src/lib/equity-chart.test.ts::leaves a series null after its own last point rather than extending it
- frontend/src/lib/equity-chart.test.ts::equity unavailable yields mode 'benchmark-only' with a note naming the reason (today's production case)
- frontend/src/lib/equity-chart.test.ts::benchmark truncated clips both series to the benchmark's newest point and the note states the cut-off date
- frontend/src/lib/equity-chart.test.ts::non-overlapping ranges yield mode 'none' with a note, and zero rows
- frontend/src/lib/equity-chart.test.ts::fewer than two aligned rows yields mode 'none' — regression guard for the two-point placeholder this slice deletes
- frontend/src/lib/equity-chart.test.ts::both series empty yields mode 'none' and a note, never a fabricated flat line

### 4. Slice 4: render model_votes so the signal feed's reasoning is complete

`model_votes: Record<string, string>` is typed at `frontend/src/lib/trading-api.ts:24` and already returned by the signal endpoint, but is never rendered, so the dashboard's 'signal feed with reasoning' currently shows only `top_features`. A user cannot see which models agreed or disagreed on a signal.

Add `frontend/src/lib/model-votes.ts` exposing pure `summariseVotes(votes, direction)` returning `{consensus, counts, perModel}` where `consensus` is `'unanimous' | 'majority' | 'split' | 'none'`, `counts` tallies votes agreeing with and dissenting from the signal direction, and `perModel` is a stably ordered list of `{model, vote, agrees}` entries whose order does not depend on input key order. Missing, empty or malformed `votes` yields `consensus: 'none'` with an empty `perModel` — never a fabricated unanimous verdict, and never an averaged-away dissent: a single dissenting model appears in `perModel` and in `counts`.

Render it in the signal card block at `frontend/src/components/trading.tsx:155-251`, as per-model vote chips plus the consensus label beside the existing `model_version`, and render the `'none'` case as an explicit 'no votes recorded' line rather than an empty region.

Fully independent of slices 1-3 and fully offline-testable: signals come from the platform API and the tests use fixture objects. No Binance, no keys, no freqtrade.

**Acceptance**

- [ ] `frontend/package.json` is unchanged. No component-test dependency is added; the extracted pure function is the unit under test, and the JSX stays thin enough that it contains no vote logic.
- [ ] All six tests committed failing first, then passing.
- [ ] Every field rendered in the signal card comes from the signal payload; no vote, model name or consensus label is inferred or defaulted when `model_votes` is absent.
- [ ] The `'none'` case renders visible 'no votes recorded' text, not an empty div.
- [ ] `tsc` and `next build` pass; the frontend CI job is green.
- [ ] One release cut via `scripts/release.py`; `scripts/ci_gate.py` green.

**Tests first**

- frontend/src/lib/model-votes.test.ts::counts votes agreeing with and dissenting from the signal direction
- frontend/src/lib/model-votes.test.ts::all models agreeing yields consensus 'unanimous' with matching counts
- frontend/src/lib/model-votes.test.ts::a 2-1 split yields consensus 'majority' and the dissenting model is present in perModel
- frontend/src/lib/model-votes.test.ts::an even disagreement yields consensus 'split'
- frontend/src/lib/model-votes.test.ts::ordering of perModel is stable and independent of input key order
- frontend/src/lib/model-votes.test.ts::missing, empty or malformed votes yields consensus 'none' and an empty perModel, never 'unanimous'
