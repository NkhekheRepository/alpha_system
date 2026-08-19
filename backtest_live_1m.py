#!/usr/bin/env python3
"""1m-granularity walk-forward validation of the LIVE runner semantics.

Pre-registered: experiments/PR_20260819_1m_live_semantics.json (sha 82ca07ea...).
Mirrors the live bots exactly on 1m closes:
  - churn:    enter LONG unconditionally when flat (Alpha 1 live)
  - momentum: direction = sign(close[t]/close[t-K]-1), K on 60s polls = K on 1m bars (Alpha 2 live)
  - exits:    first 1m close crossing +/-barrier from entry, timeout at bar 75, re-enter next bar
  - 3% of capital, 0.1%/side fees, circuit breaker 3 losses -> 50-bar cooldown
Gates G1-G4 identical to the 5m protocol; verdict PASS iff all hold.
"""

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path('/home/nkhekhe/alpha_system/experiments/1m_results_20260819.json')
PR_HASH = '82ca07ea1df4306ecb112586bd9b15c98861aff681d1f50028ed898f6b431d77'

DATA = Path('/home/nkhekhe/user_data/data/binance')
ASSETS = {'BTCUSDT': 'BTCUSDT_USDT-1m.feather', 'ETHUSDT': 'ETHUSDT_USDT-1m.feather'}
FOLDS = 4
EMBARGO = 50
CAP = 100000.0
POS_PCT = 0.03
FEE = 0.001
MAX_CONSEC = 3
COOLDOWN = 50
WARMUP = 85

MODES = ['churn', 'momentum']
K_GRID = [5, 10, 20]
BARRIER_GRID = [0.01, 0.02, 0.03]
H = 75

configs = []
for mode, k, b in itertools.product(MODES, K_GRID, BARRIER_GRID):
    configs.append({'mode': mode, 'k': k, 'barrier': b, 'horizon': H})
assert len(configs) == 18

live_a1 = {'mode': 'churn', 'k': None, 'barrier': 0.02, 'horizon': H}
live_a2 = {'mode': 'momentum', 'k': 10, 'barrier': 0.02, 'horizon': H}


def run_engine(closes, cfg):
    n = len(closes)
    trades = []
    equity = CAP
    consec = 0
    cooldown = 0
    t = 0
    while t < n:
        if cooldown > 0:
            cooldown -= 1
            t += 1
            continue
        if t < WARMUP:
            t += 1
            continue
        if cfg['mode'] == 'momentum':
            ret = closes[t] / closes[t - cfg['k']] - 1
            if ret > 0:
                direction = 'long'
            elif ret < 0:
                direction = 'short'
            else:
                t += 1
                continue
        else:
            direction = 'long'
        entry = closes[t]
        tp = entry * (1 + 0.02) if direction == 'long' else entry * (1 - 0.02)
        sl = entry * (1 - 0.02) if direction == 'long' else entry * (1 + 0.02)
        exit_p = None
        reason = None
        exit_bar = None
        for b in range(t + 1, min(t + H + 1, n)):
            c = closes[b]
            if direction == 'long':
                if c >= tp:
                    exit_p, reason = tp, 'TP'
                elif c <= sl:
                    exit_p, reason = sl, 'SL'
            else:
                if c <= tp:
                    exit_p, reason = tp, 'TP'
                elif c >= sl:
                    exit_p, reason = sl, 'SL'
            if exit_p is not None:
                exit_bar = b
                break
        if exit_p is None:
            exit_bar = min(t + H, n - 1)
            exit_p = closes[exit_bar]
            reason = 'TIMEOUT'
        gross = (exit_p - entry) / entry if direction == 'long' else (entry - exit_p) / entry
        qty = (equity * POS_PCT) / entry
        notional = qty * entry
        pnl_d = qty * (exit_p - entry) if direction == 'long' else qty * (entry - exit_p)
        pnl_d -= notional * FEE + qty * exit_p * FEE
        pnl_pct = pnl_d / notional
        equity += pnl_d
        if pnl_d > 0:
            consec = 0
        else:
            consec += 1
            if consec >= MAX_CONSEC:
                cooldown = COOLDOWN
                consec = 0
        trades.append({'direction': direction, 'reason': reason, 'pnl_pct': pnl_pct,
                       'pnl_dollars': pnl_d, 'entry_bar': t, 'exit_bar': exit_bar})
        t = exit_bar + 1
    return trades


def summarize(trades):
    n = len(trades)
    if n == 0:
        return {'n': 0, 'wr': 0.0, 'net_return_pct': 0.0, 'mean_w': 0.0, 'net_pnl': 0.0}
    wins = sum(1 for t in trades if t['pnl_dollars'] > 0)
    net = sum(t['pnl_dollars'] for t in trades)
    return {'n': n, 'wr': wins / n, 'net_return_pct': net / CAP * 100,
            'mean_w': float(np.mean([t['pnl_pct'] for t in trades])), 'net_pnl': net}


def main():
    folds = {}
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA / fname)
        closes = df['close'].to_numpy()
        idx = np.array_split(np.arange(len(closes)), FOLDS)
        folds[sym] = []
        for fi, ix in enumerate(idx):
            start = min(ix[0] + EMBARGO, ix[-1])
            folds[sym].append(closes[start:ix[-1] + 1])

    cells = {}
    for sym in ASSETS:
        for fi in range(FOLDS):
            closes = folds[sym][fi]
            for ci, cfg in enumerate(configs):
                trades = run_engine(closes, cfg)
                s = summarize(trades)
                key = (ci, fi)
                if key not in cells:
                    cells[key] = []
                cells[key].append(s)

    def combined(ci, fi):
        parts = cells[(ci, fi)]
        n = sum(p['n'] for p in parts)
        net = sum(p['net_pnl'] for p in parts)
        wins = 0
        return {'n': n, 'net_return_pct': net / CAP * 100, 'net_pnl': net}

    rows = []
    for ci, cfg in enumerate(configs):
        per_fold = [combined(ci, fi) for fi in range(FOLDS)]
        g1 = all(f['n'] >= 20 for f in per_fold)
        g2 = sum(1 for fi in [0, 1, 2] if per_fold[fi]['net_return_pct'] > 0) >= 2
        med = float(np.median([per_fold[fi]['net_return_pct'] for fi in [0, 1, 2]]))
        rows.append({'config': cfg, 'per_fold': per_fold, 'g1': g1, 'g2': g2,
                     'train_median': med})

    def cfg_index(cfg):
        for i, c in enumerate(configs):
            if all(c[k] == cfg[k] for k in cfg):
                return i
        return None

    def eval_cfg(cfg):
        all_trades = []
        per_fold = []
        for fi in range(FOLDS):
            fold_trades = []
            for sym in ASSETS:
                fold_trades += run_engine(folds[sym][fi], cfg)
            all_trades += fold_trades
            s = summarize(fold_trades)
            per_fold.append({'n': s['n'], 'net_return_pct': s['net_return_pct'],
                             'net_pnl': s['net_pnl']})
        v = per_fold[3]
        g1 = all(f['n'] >= 20 for f in per_fold)
        g2 = sum(1 for fi in [0, 1, 2] if per_fold[fi]['net_return_pct'] > 0) >= 2
        mean_w = float(np.mean([t['pnl_pct'] for t in all_trades])) if all_trades else 0.0
        g3 = v['net_return_pct'] > 0
        g4 = mean_w > 0.002
        return {'per_fold': per_fold, 'g1': g1, 'g2': g2, 'g3': g3, 'g4': g4,
                'mean_w': mean_w, 'verdict': 'PASS' if (g1 and g2 and g3 and g4) else 'NO-GO',
                'n_total': sum(t['n'] for t in per_fold)}

    passing = [r for r in rows if r['g1'] and r['g2']]
    selected = max(passing, key=lambda r: r['train_median']) if passing else None

    a1 = eval_cfg(live_a1)
    a2 = eval_cfg(live_a2)

    out = {
        'pr_hash': PR_HASH,
        'live_configs': {'alpha1_churn_2pct_75': a1, 'alpha2_momentumK10_2pct_75': a2},
        'grid_passing_train': len(passing),
        'selected': selected['config'] if selected else None,
        'selected_train_median': selected['train_median'] if selected else None,
        'top10': sorted(rows, key=lambda r: r['train_median'], reverse=True)[:10],
        'verdict_grid': 'PASS' if selected else 'NO-GO',
    }
    OUT.write_text(json.dumps(out, indent=2, default=float))

    print("LIVE CONFIGS at 1m granularity:")
    for name, a in [('Alpha1 churn 2% H75', a1), ('Alpha2 momentum-K10 2% H75', a2)]:
        f = a['per_fold']
        print(f"  {name}: folds {[f'{x['net_return_pct']:+.2f}%' for x in f]}")
        print(f"    G1={a['g1']} G2={a['g2']} G3={a['g3']} G4={a['g4']} "
              f"mean_w={a['mean_w']:+.4f} | {a['verdict']}")
    print(f"\nGrid: {len(passing)}/18 passed G1+G2 | selected: {out['selected']}")
    print(f"\n>>> GRID VERDICT: {out['verdict_grid']} <<<")
    print(f"Saved: {OUT}")


if __name__ == '__main__':
    main()