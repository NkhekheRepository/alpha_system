#!/usr/bin/env python3
"""Download 5m klines for BTC/ETH (matching the backed 5m feather data).

If the existing feathers were lost, re-download them to:
  user_data/data/binance/{BTC,ETH}_USDT-5m.feather
Window: 2024-01-01 UTC -> session end.
"""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path('/home/nkhekhe/user_data/data/binance')
from binance_config import BINANCE_API_BASE
API = f'{BINANCE_API_BASE}/api/v3/klines'
SYMBOLS = {
    'BTCUSDT': 'BTC_USDT-5m.feather',
    'ETHUSDT': 'ETH_USDT-5m.feather',
}
START = 1704067200000  # 2024-01-01 UTC


def fetch_klines(symbol, start, end, limit=1000):
    rows = []
    cur = start
    while cur < end:
        r = requests.get(API, params={
            'symbol': symbol, 'interval': '5m',
            'startTime': cur, 'endTime': end,
            'limit': limit,
        }, timeout=30)
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
    end = int(time.time() * 1000)
    for sym, fname in SYMBOLS.items():
        dest = OUT / fname
        if dest.exists():
            print(f'{sym}: cached ({dest.stat().st_size/1e6:.1f} MB)')
            continue
        print(f'{sym}: downloading 5m klines 2024-01-01 -> now ...')
        rows = fetch_klines(sym, START, end)
        df = pd.DataFrame(rows, columns=['open_time', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        for c in ['open', 'high', 'low', 'close', 'volume']:
            df[c] = df[c].astype(float)
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        df.to_feather(dest)
        print(f'{sym}: {len(df)} bars -> {dest}')


if __name__ == '__main__':
    main()
