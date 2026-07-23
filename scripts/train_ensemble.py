#!/usr/bin/env python
"""
Train the crypto ensemble on backfilled klines (issue #5) and register the
version in the model registry (issue #6).

Usage:
    DATABASE_URL=postgresql+psycopg2://... python scripts/train_ensemble.py \
        --interval 4h --folds 5 --registry models/registry
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import joblib
import pandas as pd
from sqlalchemy import create_engine

from app.models.crypto_features import FEATURE_COLUMNS
from app.models.ensemble_trainer import (
    DEFAULT_PARAMS,
    build_dataset,
    fit_ensemble,
    train_walk_forward,
)
from app.models.registry import ModelRegistry, PromotionRejected
from app.services.kline_store import load_klines
from app.services.signal_service import UNIVERSE


def main() -> int:
    parser = argparse.ArgumentParser(description="Train crypto ensemble")
    parser.add_argument("--interval", default="4h", choices=["1h", "4h", "1d"])
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--min-train", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--registry", default="models/registry")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "sqlite:///data/klines.db"),
    )
    args = parser.parse_args()

    engine = create_engine(args.database_url.replace("postgresql+asyncpg", "postgresql"))

    frames_X, frames_y = [], []
    window_start, window_end = None, None
    for symbol in UNIVERSE:
        ohlcv = load_klines(engine, symbol, args.interval)
        if len(ohlcv) < 300:
            print(f"skipping {symbol}: only {len(ohlcv)} candles")
            continue
        X, y, times = build_dataset(ohlcv)
        frames_X.append(X)
        frames_y.append(y)
        window_start = min(window_start or times.iloc[0], times.iloc[0])
        window_end = max(window_end or times.iloc[-1], times.iloc[-1])
        print(f"{symbol}: {len(X)} rows")

    X = pd.concat(frames_X, ignore_index=True)
    y = pd.concat(frames_y, ignore_index=True)
    print(f"pooled dataset: {len(X)} rows x {len(X.columns)} features")

    result = train_walk_forward(X, y, n_folds=args.folds,
                                min_train=args.min_train, seed=args.seed)
    for i, fold in enumerate(result["folds"]):
        print(f"fold {i}: accuracy {fold['directional_accuracy']:.4f} "
              f"(n={fold['n_test']})")
    aggregate = result["aggregate"]
    print(f"aggregate walk-forward accuracy: "
          f"{aggregate['directional_accuracy']:.4f} (n={aggregate['n_test']})")

    # Final model: fit on all data (walk-forward already measured honesty).
    models = fit_ensemble(X, y, DEFAULT_PARAMS, args.seed)

    registry = ModelRegistry(args.registry)
    version_id = datetime.now(timezone.utc).strftime(
        f"ensemble-{args.interval}-v%Y%m%d%H%M"
    )
    artifact_dir = registry.artifact_dir(version_id)
    for name, model in models.items():
        joblib.dump(model, artifact_dir / f"{name}.joblib")
    (artifact_dir / "manifest.json").write_text(json.dumps({
        "feature_columns": FEATURE_COLUMNS,
        "interval": args.interval,
        "params": DEFAULT_PARAMS,
        "seed": args.seed,
        "folds": result["folds"],
    }, indent=2, default=str))

    registry.register(
        version_id=version_id,
        metrics={"directional_accuracy": aggregate["directional_accuracy"],
                 "n_test": aggregate["n_test"]},
        feature_schema=FEATURE_COLUMNS,
        training_window={"start": str(window_start), "end": str(window_end)},
    )
    try:
        registry.promote(version_id)
        print(f"registered and promoted {version_id}")
    except PromotionRejected as exc:
        print(f"registered {version_id}; promotion REJECTED: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
