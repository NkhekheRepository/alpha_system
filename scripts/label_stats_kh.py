#!/usr/bin/env python3
"""Fast label-only stats for K/H grid at TP 3% / SL 1.5% (no features, no RF).

Uses multiprocessing per symbol. Prints WR / timeout% / n_labeled per config.
Output: models/label_stats_kh_tp3_sl15.json
"""
import sys, json, itertools
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_labels import compute_labels_vectorized

KLINE_DIR = Path(__file__).resolve().parent.parent / 'models' / 'kline_data'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'label_stats_kh_tp3_sl15.json'

HOLDINGS = ['TRIAUSDT','QUSDT','MAGMAUSDT','TRADOORUSDT','APRUSDT','UAIUSDT','DOODUSDT','BULLAUSDT','JCTUSDT','ZECUSDT']
TP_PCT, SL_PCT = 0.03, -0.015
K_GRID, H_GRID = [20,30,40,60], [50,75,100]

def load_sym(sym):
    df = pd.read_csv(KLINE_DIR / f"{sym}_1m.csv").sort_values('open_time').reset_index(drop=True)
    return (sym, df['close'].values.astype(np.float64), df['high'].values.astype(np.float64),
            df['low'].values.astype(np.float64))

def label_one(args):
    sym, closes, highs, lows, K, H = args
    labels, bbars, dirs, entries = compute_labels_vectorized(closes, highs, lows, k=K, h=H, tp=TP_PCT, sl=SL_PCT)
    n_tp = int(np.nansum(labels == 1)); n_sl = int(np.nansum(labels == 0))
    n_to = int(np.sum(np.isnan(labels))); n = len(labels)
    return dict(symbol=sym, n=n, tp=n_tp, sl=n_sl, timeout=n_to)

def main():
    import time as _t
    print("Loading klines once...", flush=True)
    cache = {}
    for sym in HOLDINGS:
        s, c, h, l = load_sym(sym)
        cache[s] = (c, h, l)
    print(f"Loaded {len(cache)} symbols", flush=True)
    results = []
    cfgs = list(itertools.product(K_GRID, H_GRID))
    print(f"Grid {len(cfgs)} configs at TP {TP_PCT} SL {SL_PCT}\n", flush=True)
    for K, H in cfgs:
        t0 = _t.time()
        args = [(s, cache[s][0], cache[s][1], cache[s][2], K, H) for s in HOLDINGS]
        with ProcessPoolExecutor(max_workers=4) as ex:
            per = list(ex.map(label_one, args))
        n = sum(p['n'] for p in per); tp = sum(p['tp'] for p in per)
        sl = sum(p['sl'] for p in per); to = sum(p['timeout'] for p in per)
        lab = tp + sl
        wr = 100*tp/lab if lab else 0
        tor = 100*to/n if n else 0
        r = dict(K=K, H=H, n_total=n, n_labeled=lab, n_tp=tp, n_sl=sl, n_timeout=to,
                 wr=round(wr,2), timeout_pct=round(tor,2), per_symbol=per)
        results.append(r)
        print(f"K={K:2d} H={H:3d}: {n:,} sig -> {lab:,} labeled (TP{tp} SL{sl} WR{wr:.1f}% TO{tor:.1f}%) [{_t.time()-t0:.0f}s]", flush=True)
    json.dump({'config': {'K_GRID': K_GRID, 'H_GRID': H_GRID, 'TP_PCT': TP_PCT, 'SL_PCT': SL_PCT},
               'results': results}, open(OUT_FILE, 'w'), indent=2)
    print(f"\nSaved: {OUT_FILE}", flush=True)
    print("\nRanked by WR (higher = easier TP):", flush=True)
    for r in sorted(results, key=lambda x: x['wr'], reverse=True):
        print(f"  K={r['K']:2d} H={r['H']:3d} WR{r['wr']:.1f}% TO{r['timeout_pct']:.1f}% n={r['n_labeled']:,}", flush=True)
    print("\nRanked by timeout% (lower = more decisive):", flush=True)
    for r in sorted(results, key=lambda x: x['timeout_pct']):
        print(f"  K={r['K']:2d} H={r['H']:3d} TO{r['timeout_pct']:.1f}% WR{r['wr']:.1f}% n={r['n_labeled']:,}", flush=True)

if __name__ == '__main__':
    main()
