#!/usr/bin/env python3
"""Incrementally sync kline feathers (1m/5m) with Binance (append from last stored bar)."""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path('/home/nkhekhe/user_data/data/binance')
from binance_config import BINANCE_API_BASE
API = f'{BINANCE_API_BASE}/api/v3/klines'
SYMBOLS = ['BTCUSDT', 'ETHUSDT']
INTERVALS = ['1m', '5m']
COLS = ['date', 'open', 'high', 'low', 'close', 'volume']


def fetch_klines(symbol, interval, start, end, limit=1000):
    rows = []
    cur = start
    while cur < end:
        r = requests.get(API, params={'symbol': symbol, 'interval': interval,
                                      'startTime': cur, 'endTime': end,
                                      'limit': limit}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + 1
        if len(batch) < limit:
            break
        time.sleep(0.15)
    return rows


def sync(symbol, interval):
    dest = OUT / f'{symbol}_USDT-{interval}.feather'
    if not dest.exists():
        alt = OUT / f'{symbol.replace("USDT", "")}_USDT-{interval}.feather'
        if alt.exists():
            dest = alt
    if not dest.exists():
        print(f'{symbol} {interval}: no local feather - run download script first')
        return
    df = pd.read_feather(dest)
    last_ms = int(pd.to_datetime(df['date']).max().value // 1_000_000)
    now_ms = int(time.time() * 1000)
    gap_min = (now_ms - last_ms) // 60000
    if gap_min < 2:
        print(f'{symbol}: already current (last bar {gap_min} min ago)')
        return
    print(f'{symbol} {interval}: fetching {gap_min:,} bars ({gap_min * (1 if interval=="1m" else 5)//60}h {gap_min * (1 if interval=="1m" else 5)%60}m gap) ...')
    raw = fetch_klines(symbol, interval, last_ms + 1, now_ms)
    if not raw:
        print(f'{symbol} {interval}: nothing returned')
        return
    new = pd.DataFrame([r[:6] for r in raw],
                       columns=['open_time', 'open', 'high', 'low',
                                'close', 'volume'])
    new['date'] = pd.to_datetime(new['open_time'], unit='ms', utc=True)
    for c in ['open', 'high', 'low', 'close', 'volume']:
        new[c] = new[c].astype(float)
    new = new[COLS]
    merged = pd.concat([df, new], ignore_index=True)
    merged = merged.drop_duplicates(subset='date', keep='last')
    merged = merged.sort_values('date').reset_index(drop=True)
    added = len(merged) - len(df)
    merged.to_feather(dest)
    last = pd.to_datetime(merged['date']).max()
    print(f'{symbol} {interval}: +{added:,} bars | total {len(merged):,} | last {last} UTC')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for interval in INTERVALS:
        for sym in SYMBOLS:
            try:
                sync(sym, interval)
            except Exception as e:
                print(f'{sym} {interval}: ERROR {e}')


if __name__ == '__main__':
    main()
