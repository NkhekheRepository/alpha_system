#!/usr/bin/env python3
"""Download 1m klines for live-granularity backtesting (cached to feather)."""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path('/home/nkhekhe/user_data/data/binance')
API = 'https://api.binance.com/api/v3/klines'
SYMBOLS = ['BTCUSDT', 'ETHUSDT']
START = 1735689600000 if '--full' in sys.argv else 1767225600000  # 2025-01-01 / 2026-01-01 UTC
END = int(time.time() * 1000)


def fetch_klines(symbol, start, end, limit=1000):
    rows = []
    cur = start
    while cur < end:
        r = requests.get(API, params={'symbol': symbol, 'interval': '1m',
                                      'startTime': cur, 'endTime': end,
                                      'limit': limit}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for k in batch:
            rows.append([k[0], k[1], k[2], k[3], k[4], k[5]])
        cur = batch[-1][0] + 1
        if len(batch) < limit:
            break
        time.sleep(0.15)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        dest = OUT / f'{sym}_USDT-1m.feather'
        if dest.exists():
            print(f'{sym}: cached ({dest.stat().st_size/1e6:.1f} MB)')
            continue
        print(f'{sym}: downloading 1m klines 2025-01-01 -> now ...')
        rows = fetch_klines(sym, START, END)
        df = pd.DataFrame(rows, columns=['open_time', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        for c in ['open', 'high', 'low', 'close', 'volume']:
            df[c] = df[c].astype(float)
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        df.to_feather(dest)
        print(f'{sym}: {len(df)} bars -> {dest}')


if __name__ == '__main__':
    main()