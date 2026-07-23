#!/usr/bin/env python
"""
Run the live kline websocket consumer (issue #3).

Usage:
    DATABASE_URL=postgresql+psycopg2://... python scripts/stream_klines.py --interval 4h
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine

from app.services.kline_store import create_tables
from app.services.kline_stream import KlineStreamConsumer
from app.services.signal_service import UNIVERSE


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream Binance klines")
    parser.add_argument("--interval", default="4h", choices=["1h", "4h", "1d"])
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "sqlite:///data/klines.db"),
    )
    args = parser.parse_args()

    engine = create_engine(args.database_url.replace("postgresql+asyncpg", "postgresql"))
    create_tables(engine)

    heartbeat_fn = None
    heartbeat_url = os.environ.get("HEALTHCHECKS_URL")
    if heartbeat_url:
        import httpx

        def heartbeat_fn():
            httpx.get(heartbeat_url, timeout=5.0)

    consumer = KlineStreamConsumer(
        engine, list(UNIVERSE), args.interval, heartbeat_fn=heartbeat_fn
    )
    asyncio.run(consumer.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
