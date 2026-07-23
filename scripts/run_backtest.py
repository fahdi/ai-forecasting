#!/usr/bin/env python
"""
G0 gate: walk-forward backtest vs BTC buy-and-hold (issue #11, PRD §8).

Trains the ensemble per fold on past data only, tunes the entry threshold on
the train tail, simulates long/flat trading with fees+slippage on the unseen
test window, and writes docs/gates/G0-report.md with a go/no-go verdict.

Usage:
    DATABASE_URL=... python scripts/run_backtest.py --folds 5
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from app.backtest.engine import (
    BINANCE_TAKER_FEE,
    DEFAULT_SLIPPAGE,
    max_drawdown,
    sharpe_ratio,
    simulate_long_flat,
)
from app.models.ensemble_trainer import (
    DEFAULT_PARAMS,
    build_dataset,
    fit_ensemble,
    predict_prob_long,
    walk_forward_splits,
)
from app.services.kline_store import load_klines
from app.services.signal_service import UNIVERSE

PERIODS_PER_YEAR = 6 * 365  # 4h bars
THRESHOLD_GRID = [0.50, 0.55, 0.60, 0.65, 0.70]
STOP_LOSS = 0.05
MAX_HOLD_BARS = 30  # 5 days of 4h bars
TUNE_TAIL_FRACTION = 0.15


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--min-train", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "sqlite:///data/klines.db"),
    )
    args = parser.parse_args()
    engine = create_engine(args.database_url.replace("postgresql+asyncpg", "postgresql"))

    datasets = {}
    for symbol in UNIVERSE:
        ohlcv = load_klines(engine, symbol, "4h")
        X, y, times = build_dataset(ohlcv)
        close = ohlcv.set_index("open_time")["close"].reindex(times).reset_index(drop=True)
        datasets[symbol] = {"X": X, "y": y, "times": times, "close": close}
        print(f"{symbol}: {len(X)} rows")

    n = min(len(d["X"]) for d in datasets.values())
    folds = walk_forward_splits(n=n, n_folds=args.folds, min_train=args.min_train)

    pair_equities = {s: [] for s in datasets}
    pair_trades = {s: 0 for s in datasets}
    chosen_thresholds = []
    test_times = []

    for fold_no, (train_end, test_start, test_end) in enumerate(folds):
        X_train = pd.concat([d["X"].iloc[:train_end] for d in datasets.values()],
                            ignore_index=True)
        y_train = pd.concat([d["y"].iloc[:train_end] for d in datasets.values()],
                            ignore_index=True)
        models = fit_ensemble(X_train, y_train, DEFAULT_PARAMS, args.seed)

        # Threshold tuning on the TRAIN TAIL only (never test data).
        tail_start = int(train_end * (1 - TUNE_TAIL_FRACTION))
        best_threshold, best_score = None, -np.inf
        for threshold in THRESHOLD_GRID:
            scores = []
            for d in datasets.values():
                prob = predict_prob_long(models, d["X"].iloc[tail_start:train_end])
                sim = simulate_long_flat(
                    d["close"].iloc[tail_start:train_end].reset_index(drop=True),
                    pd.Series(prob), threshold,
                    stop_loss=STOP_LOSS, max_hold_bars=MAX_HOLD_BARS)
                scores.append(sim["equity"].iloc[-1])
            score = float(np.mean(scores))
            if score > best_score:
                best_threshold, best_score = threshold, score
        chosen_thresholds.append(best_threshold)

        for symbol, d in datasets.items():
            prob = predict_prob_long(models, d["X"].iloc[test_start:test_end])
            sim = simulate_long_flat(
                d["close"].iloc[test_start:test_end].reset_index(drop=True),
                pd.Series(prob), best_threshold,
                stop_loss=STOP_LOSS, max_hold_bars=MAX_HOLD_BARS)
            pair_equities[symbol].append(sim["equity"])
            pair_trades[symbol] += sim["n_trades"]
        test_times.append((datasets["BTCUSDT"]["times"].iloc[test_start],
                           datasets["BTCUSDT"]["times"].iloc[test_end - 1]))
        print(f"fold {fold_no}: threshold {best_threshold}")

    # Stitch folds per pair, then equal-weight portfolio.
    stitched = {}
    for symbol, chunks in pair_equities.items():
        curve, level = [], 1.0
        for chunk in chunks:
            curve.append(chunk * level)
            level = curve[-1].iloc[-1]
        stitched[symbol] = pd.concat(curve, ignore_index=True)
    portfolio = pd.concat(stitched.values(), axis=1).mean(axis=1)

    # Benchmark: BTC buy-and-hold over the same stitched window.
    d = datasets["BTCUSDT"]
    btc_close = d["close"].iloc[folds[0][1]:folds[-1][2]].reset_index(drop=True)
    benchmark = btc_close / btc_close.iloc[0] * (1 - BINANCE_TAKER_FEE - DEFAULT_SLIPPAGE) ** 2

    strategy = {
        "return": float(portfolio.iloc[-1] - 1),
        "sharpe": sharpe_ratio(portfolio, PERIODS_PER_YEAR),
        "max_drawdown": max_drawdown(portfolio),
        "trades": sum(pair_trades.values()),
    }
    bench = {
        "return": float(benchmark.iloc[-1] - 1),
        "sharpe": sharpe_ratio(benchmark, PERIODS_PER_YEAR),
        "max_drawdown": max_drawdown(benchmark),
    }
    go = (strategy["sharpe"] > bench["sharpe"]
          and strategy["max_drawdown"] < 0.25
          and strategy["return"] > 0)

    window = f"{test_times[0][0]} → {test_times[-1][1]}"
    print(f"\nOut-of-sample window: {window}")
    print(f"strategy:  return {strategy['return']:+.2%}  sharpe {strategy['sharpe']:.2f}  "
          f"maxDD {strategy['max_drawdown']:.2%}  trades {strategy['trades']}")
    print(f"benchmark: return {bench['return']:+.2%}  sharpe {bench['sharpe']:.2f}  "
          f"maxDD {bench['max_drawdown']:.2%}")
    print(f"G0 verdict: {'GO' if go else 'NO-GO'}")

    os.makedirs("docs/gates", exist_ok=True)
    per_pair_lines = "\n".join(
        f"| {UNIVERSE[s]} | {stitched[s].iloc[-1] - 1:+.2%} | {pair_trades[s]} |"
        for s in stitched
    )
    report = f"""# G0 Gate Report — Walk-Forward Backtest

Generated: {datetime.now(timezone.utc).isoformat()}
Method: {args.folds}-fold walk-forward; ensemble retrained per fold on past
data only; entry threshold tuned per fold on the train tail
({THRESHOLD_GRID}, chosen: {chosen_thresholds}); fees {BINANCE_TAKER_FEE:.2%}
+ slippage {DEFAULT_SLIPPAGE:.3%} per side; stop-loss {STOP_LOSS:.0%};
max hold {MAX_HOLD_BARS} bars. Portfolio = equal-weight across the 4 pairs.

Out-of-sample window: {window}

| Metric | Strategy | BTC buy-and-hold |
|---|---|---|
| Total return | {strategy['return']:+.2%} | {bench['return']:+.2%} |
| Sharpe (annualized) | {strategy['sharpe']:.2f} | {bench['sharpe']:.2f} |
| Max drawdown | {strategy['max_drawdown']:.2%} | {bench['max_drawdown']:.2%} |
| Trades | {strategy['trades']} | 1 |

Per-pair out-of-sample results:

| Pair | Return | Trades |
|---|---|---|
{per_pair_lines}

## PRD §8 G0 criteria

- Sharpe beats buy-and-hold: {"✅" if strategy['sharpe'] > bench['sharpe'] else "❌"} ({strategy['sharpe']:.2f} vs {bench['sharpe']:.2f})
- Max drawdown < 25%: {"✅" if strategy['max_drawdown'] < 0.25 else "❌"} ({strategy['max_drawdown']:.2%})
- Positive after fees: {"✅" if strategy['return'] > 0 else "❌"} ({strategy['return']:+.2%})

## Verdict: **{"GO" if go else "NO-GO"}**

{"All G0 criteria pass; proceed to G1 paper trading." if go else "G0 criteria not met. Per the PRD, no capital is deployed and no G1 paper run starts until a model iteration passes this gate. This outcome costs nothing — it is the gate doing its job."}
"""
    with open("docs/gates/G0-report.md", "w") as f:
        f.write(report)
    print("report: docs/gates/G0-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
