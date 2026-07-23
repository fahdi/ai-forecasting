# G0 Gate Report — Walk-Forward Backtest

Generated: 2026-07-23T21:00:58.517160+00:00
Method: 5-fold walk-forward; ensemble retrained per fold on past
data only; entry threshold tuned per fold on the train tail
([0.5, 0.55, 0.6, 0.65, 0.7], chosen: [0.5, 0.5, 0.55, 0.55, 0.55]); fees 0.10%
+ slippage 0.050% per side; stop-loss 5%;
max hold 30 bars. Portfolio = equal-weight across the 4 pairs.

Out-of-sample window: 2025-06-30 00:00:00+00:00 → 2026-07-23 12:00:00+00:00

| Metric | Strategy | BTC buy-and-hold |
|---|---|---|
| Total return | -78.76% | -40.31% |
| Sharpe (annualized) | -4.75 | -0.96 |
| Max drawdown | 79.80% | 53.45% |
| Trades | 1555 | 1 |

Per-pair out-of-sample results:

| Pair | Return | Trades |
|---|---|---|
| BTC/USDT | -82.16% | 365 |
| ETH/USDT | -79.12% | 389 |
| SOL/USDT | -82.34% | 486 |
| BNB/USDT | -71.43% | 315 |

## PRD §8 G0 criteria

- Sharpe beats buy-and-hold: ❌ (-4.75 vs -0.96)
- Max drawdown < 25%: ❌ (79.80%)
- Positive after fees: ❌ (-78.76%)

## Verdict: **NO-GO**

G0 criteria not met. Per the PRD, no capital is deployed and no G1 paper run starts until a model iteration passes this gate. This outcome costs nothing — it is the gate doing its job.
