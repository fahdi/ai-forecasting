#!/usr/bin/env python
"""
Backfill Binance klines into the database (issue #2).

Usage:
    python scripts/backfill_klines.py --pair BTC/USDT --interval 4h --years 2
    python scripts/backfill_klines.py --all --interval 4h --years 2

DATABASE_URL env var (or --database-url) selects the target database.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine

from app.services.kline_backfill import backfill, fetch_binance_page
from app.services.kline_store import count_klines, create_tables, find_gaps
from app.services.signal_service import UNIVERSE, normalize_pair


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Binance klines")
    parser.add_argument("--pair", help="Pair, e.g. BTC/USDT")
    parser.add_argument("--all", action="store_true", help="Backfill the whole universe")
    parser.add_argument("--interval", default="4h", choices=["1h", "4h", "1d"])
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "sqlite:///data/klines.db"),
    )
    args = parser.parse_args()

    if args.all:
        symbols = list(UNIVERSE)
    elif args.pair:
        symbol = normalize_pair(args.pair)
        if symbol is None:
            print(f"error: pair '{args.pair}' not in universe {sorted(UNIVERSE.values())}")
            return 1
        symbols = [symbol]
    else:
        parser.error("--pair or --all required")

    url = args.database_url
    if url.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(url.replace("sqlite:///", "")) or ".", exist_ok=True)
    engine = create_engine(url.replace("postgresql+asyncpg", "postgresql"))
    create_tables(engine)

    start_ms = int((time.time() - args.years * 365.25 * 86400) * 1000)
    for symbol in symbols:
        stored = backfill(fetch_binance_page, engine, symbol, args.interval, start_ms)
        total = count_klines(engine, symbol, args.interval)
        gaps = find_gaps(engine, symbol, args.interval)
        print(f"{symbol} {args.interval}: fetched {stored}, in db {total}, gaps {len(gaps)}")
        for gap_start, gap_end in gaps[:10]:
            print(f"  gap: {gap_start} -> {gap_end}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
