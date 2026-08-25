#!/usr/bin/env python3
"""Fetch historical 1m klines from Binance for meta-labeler training.

Paginates through the public klines API (no auth required).
Stores per-symbol CSVs in models/kline_data/.

Usage:
    python3 scripts/fetch_historical_klines.py [--months 6] [--symbols BTCUSDT,ETHUSDT]
"""

import argparse, csv, sys, time
from datetime import datetime, timedelta
from pathlib import Path

import requests

API_BASE = 'https://api.binance.com/api/v3'
DATA_DIR = Path(__file__).resolve().parent.parent / 'models' / 'kline_data'
DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ZECUSDT']
LIMIT = 1000  # max per request


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    """Fetch all 1m klines between start_ms and end_ms for a symbol."""
    all_klines = []
    cursor = start_ms
    while cursor < end_ms:
        params = {'symbol': symbol, 'interval': '1m', 'startTime': cursor,
                  'endTime': end_ms, 'limit': LIMIT}
        for attempt in range(5):
            try:
                r = requests.get(f"{API_BASE}/klines", params=params, timeout=15)
                if r.status_code == 429:
                    wait = int(r.headers.get('Retry-After', 10))
                    print(f"    rate-limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    print(f"    FATAL: {symbol} fetch failed after 5 attempts: {e}")
                    return all_klines
                time.sleep(2 ** attempt)
        if not data:
            break
        all_klines.extend(data)
        cursor = data[-1][6] + 1  # close_time + 1ms
        if len(data) < LIMIT:
            break
        time.sleep(0.05)  # gentle rate limiting
    return all_klines


def save_klines(symbol: str, klines: list[list], out_dir: Path):
    """Save klines to CSV: open_time,open,high,low,close,volume,close_time."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol}_1m.csv"
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time'])
        for k in klines:
            w.writerow([k[0], k[1], k[2], k[3], k[4], k[5], k[6]])
    return path


def main():
    ap = argparse.ArgumentParser(description='Fetch Binance 1m klines')
    ap.add_argument('--months', type=int, default=6, help='Months of history')
    ap.add_argument('--symbols', type=str, default=','.join(DEFAULT_SYMBOLS),
                    help='Comma-separated symbols')
    args = ap.parse_args()

    symbols = args.symbols.split(',')
    end_ms = int(time.time() * 1000)
    start_ms = int((datetime.utcnow() - timedelta(days=args.months * 30)).timestamp() * 1000)

    print(f"Fetching {args.months}m of 1m klines: {', '.join(symbols)}")
    print(f"Range: {datetime.utcfromtimestamp(start_ms/1000)} -> {datetime.utcfromtimestamp(end_ms/1000)}")
    print(f"Output: {DATA_DIR}\n")

    for sym in symbols:
        t0 = time.time()
        klines = fetch_klines(sym, start_ms, end_ms)
        path = save_klines(sym, klines, DATA_DIR)
        elapsed = time.time() - t0
        days = (klines[-1][0] - klines[0][0]) / 86400000 if len(klines) > 1 else 0
        print(f"  {sym}: {len(klines):,} bars ({days:.0f}d) -> {path.name} ({elapsed:.1f}s)")

    print(f"\nDone. {len(symbols)} symbols fetched.")


if __name__ == '__main__':
    main()
