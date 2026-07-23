# Risk limits — PRD §7 mapping (issue #10)

How each hard limit from `docs/PRD-trading-bot.md` §7 is enforced in the
Freqtrade layer (`user_data/config.dry.json` + `EnsembleSignalStrategy`), and
where Freqtrade's primitives fall short of the PRD's exact wording.

## Position sizing arithmetic

- Risk per trade = position size × stop distance.
- Hard stop is **-5%** (`EnsembleSignalStrategy.stoploss = -0.05`).
- A 2% portfolio risk budget therefore allows a position of
  `2% / 5% = 40%` of the portfolio (the position cap).
- Config uses `stake_amount: "unlimited"` + `max_open_trades: 3` +
  `tradable_balance_ratio: 0.99`, so each trade stakes
  `0.99 / 3 ≈ 33%` of the portfolio — under the 40% cap, worst-case
  **~1.65% risk per trade** (33% × 5%).
- Worst case with all 3 slots open and every stop hit: **~4.95%** of the
  portfolio — aligned with the daily -5% circuit breaker below.

## PRD §7 limit → enforcing mechanism → verification

| PRD §7 limit | Value | Enforcing mechanism | Verification status |
|---|---|---|---|
| Risk per trade | ≤ 2% of portfolio | `stake_amount: "unlimited"` + `max_open_trades: 3` + `tradable_balance_ratio: 0.99` in `config.dry.json`, combined with the -5% strategy stop (arithmetic above) | Verified by `tests/test_ensemble_strategy.py::TestRiskConfiguration` (config values + `stoploss == -0.05`) |
| Concurrent positions | ≤ 3 | `max_open_trades: 3` in `config.dry.json` | Verified by test (`test_max_open_trades`) |
| Stop-loss per position | Hard stop, on exchange (R10) | `stoploss = -0.05` on the strategy; `order_types.stoploss_on_exchange: true` in config; trailing stop (`trailing_stop = True`, +2% trail after +4% offset) ratchets it | Verified by tests (`test_stoploss_on_exchange`, `test_strategy_hard_stop_5_percent`, `test_strategy_trailing_stop_enabled`). Exchange-side placement itself only observable in live/dry-run against the exchange |
| Daily loss circuit breaker | -5% day → halt new entries until manual review | `MaxDrawdown` protection on the strategy: 24h lookback (`lookback_period_candles: 24` on 1h), `max_allowed_drawdown: 0.05`, `stop_duration_candles: 1440` (~60 days ≈ "until manual review") — **approximation, see gaps** | Protection presence + values verified by test (`test_protections_present`); behavioral trip not covered by unit tests |
| Max drawdown kill | -15% from equity peak → full halt, stakeholder review to restart | `MaxDrawdown` protection: 30-day lookback (720 candles), `max_allowed_drawdown: 0.15`, `stop_duration_candles: 43200` (~5 years ≈ permanent) — **approximation, see gaps** | Protection presence + values verified by test; behavioral trip not covered |
| (supporting) repeated stopouts | — | `StoplossGuard`: 4 stops in 24h → halt all pairs for 24h | Presence verified by test |
| Signal staleness | > 2 cycles stale → no new entries (R9) | Strategy guard: `stale: true` (computed server-side in `app/services/signal_service.py`) or any API failure → no entry, fail-closed | Verified by tests (`test_stale_signal_blocks_entry`, `test_api_failure_fails_closed`, `test_client_exception_fails_closed_and_does_not_raise`) |
| Key permissions | Trade-only, no withdrawal, IP-locked | **Not expressible in Freqtrade** — enforced at Binance API-key creation time (R16). Dry-run config carries empty keys | Manual checklist item before any live rollout |

## Gaps between PRD §7 and Freqtrade protections

1. **"Until manual review" / "stakeholder review required" is not a Freqtrade
   concept.** Protections halt trading for a fixed candle count. We
   approximate "manual review" with very long `stop_duration_candles`
   (60 days for the daily breaker, ~5 years for the -15% kill). A restart
   before that requires an operator to restart the bot / clear the lock —
   which is effectively the manual review, but Freqtrade cannot *demand* it.
2. **Daily breaker is a rolling 24h drawdown, not a calendar-day P&L.**
   Freqtrade's `MaxDrawdown` measures drawdown across *closed* trades within
   `lookback_period_candles`. PRD's "-5% day" reads as calendar-day equity
   change including open positions. Two consequences:
   - unrealized losses do not trip it until trades close;
   - it needs at least `trade_limit` closed trades in the window to evaluate.
   A faithful calendar-day, mark-to-market breaker would need a custom
   protection plugin or an external watchdog (PRD R14 alerting) — deferred.
3. **-15% kill measures drawdown over its lookback window, not "from
   all-time equity peak".** A peak older than the 30-day lookback is
   invisible to it. Same remediation path as (2).
4. **Protections only block new entries / new position-opens.** Open trades
   still exit via stop/trailing/exit-signal, which matches PRD intent
   ("halt all new entries", manage existing to exit).
5. **Protections live on the strategy, not in `config.dry.json`.** Freqtrade
   removed config-level `protections`; they are defined in
   `EnsembleSignalStrategy.protections`. The issue #10 test asserts them on
   the loaded strategy class instead of the raw config.
