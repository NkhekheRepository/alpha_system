#!/usr/bin/env python3
"""Kelly criterion test on synthetic data — DEEP config (Alpha 2%, TP/SL 2%, H=15, K=10).

Scenarios:
  S1  Deep REAL causal distribution (10,719 trades, 29.6% WR, 0.1%/side fees embedded)
  S2  Known-bugged W9 synthetic assumption (84/85/86% WR, iid +/-2% wager returns, no fees)
      (the 84-86% WR numbers came from pnl_dollars = 100000.0 * pnl_pct, 100% notional)

MC: 2,000 bootstrap paths per fraction; T = 10,719 trades per path (same count both
scenarios for comparability). S1 resamples the real Deep trade list; S2 draws iid.

Kelly: classic p/a - q/b on wager-level returns, plus numerical argmax of E[log(1+f*w)].
Constraint: discrete -2% barrier -> f must stay < 1/a = 50x or a single loss wipes
the account; full Kelly at 85% WR = 35x violates practical risk bounds.

Gate: synthetic results never authorize sizing changes (Wave 9 lesson).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '/home/nkhekhe/alpha_system')
from backtest_alpha2 import run_strategy, ASSETS, DATA_DIR, CAP, FEE

OUT = Path('/home/nkhekhe/alpha_system/kelly_results.json')
N_PATHS = 2000
SEED = 42


def load_deep_trades():
    all_trades = []
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        trades, _, _ = run_strategy(df, capital=CAP, fees=FEE)
        all_trades.extend(trades)
    return all_trades


def kelly_formula(w):
    wins = w[w > 0]
    losses = w[w < 0]
    p = len(wins) / len(w)
    b = wins.mean() if len(wins) else 0.0
    a = abs(losses.mean()) if len(losses) else 1.0
    f_star = p / a - (1 - p) / b if b > 0 else 0.0
    return p, b, a, f_star


def kelly_numeric(w, f_grid):
    best_f, best_g = 0.0, -np.inf
    for f in f_grid:
        growth = np.mean(np.log(np.maximum(1.0 + f * w, 1e-12)))
        if growth > best_g:
            best_g, best_f = growth, f
    return best_f, best_g


def simulate(w, fraction, n_paths=N_PATHS, n_trades=None):
    rng = np.random.default_rng(SEED)
    n_trades = n_trades or len(w)
    med_final = []
    p05_final = []
    med_dd = []
    p95_dd = []
    ruin_50 = []
    ruin_dd90 = []
    CAP_EQ = 1e15
    for _ in range(n_paths):
        if fraction == 0.0:
            draws = np.zeros(n_trades)
        else:
            draws = rng.choice(w, size=n_trades, replace=True)
        log_eq = np.cumsum(np.log(np.maximum(1.0 + fraction * draws, 1e-300)))
        dd = 1.0 - np.exp(log_eq - np.maximum.accumulate(log_eq))
        final = np.exp(log_eq[-1])
        if final > CAP_EQ or not np.isfinite(final):
            final = CAP_EQ
        med_final.append(final)
        p05_final.append(final)
        med_dd.append(dd.max())
        p95_dd.append(dd.max())
        ruin_50.append(final < 0.5)
        ruin_dd90.append(dd.max() >= 0.90)
    return {
        'median_final': float(np.median(med_final)),
        'p05_final': float(np.percentile(p05_final, 5)),
        'median_maxdd': float(np.median(med_dd)),
        'p95_maxdd': float(np.percentile(p95_dd, 95)),
        'ruin_p50': float(np.mean(ruin_50)),
        'ruin_p_dd90': float(np.mean(ruin_dd90)),
    }


def fmt(m, cap_100k=True):
    eq = m['median_final']
    if eq >= 1e12:
        r = ">$1e12"
    elif cap_100k:
        r = f"${eq*CAP:,.0f}"
    else:
        r = f"x{eq:.2f}"
    return (f"{r:>12s} | P05 ${m['p05_final']*CAP:,.0f} | "
            f"MedDD {m['median_maxdd']:.1%} | P95DD {m['p95_maxdd']:.1%} | "
            f"ruin(50%) {m['ruin_p50']:.1%} | ruin(DD90) {m['ruin_p_dd90']:.1%}")


def main():
    rng = np.random.default_rng(SEED)
    report = {'generated': '2026-08-19', 'config': 'DEEP (TP2%/SL2%/H15/K10/fees0.1%/3%pos)'}

    trades = load_deep_trades()
    w_real = np.array([t['pnl_pct'] for t in trades])
    wins = sum(1 for t in trades if t['pnl_pct'] > 0)
    n = len(trades)
    wr_real = wins / n
    total_pnl = sum(t['pnl_dollars'] for t in trades)
    print(f"S1 real Deep distribution: {n} trades, WR {wr_real:.1%}, "
          f"mean w {w_real.mean():+.4f}, net PnL ${total_pnl:+,.0f}")

    scenarios = {}

    s1 = {'label': 'Deep REAL causal (29% WR, fees in)'}
    f_grid_s1 = np.concatenate([[0.0], np.arange(0.01, 0.11, 0.01), [1.0]])
    p, b, a, f_f = kelly_formula(w_real)
    f_n, g_n = kelly_numeric(w_real, f_grid_s1)
    s1['kelly_formula'] = {'p': float(p), 'b': float(b), 'a': float(a), 'f_star': float(f_f)}
    s1['kelly_numeric'] = {'f_star': float(f_n), 'growth': float(g_n)}
    s1['stats'] = {'n_trades': n, 'wr': float(wr_real), 'mean_w': float(w_real.mean()),
                   'net_pnl': float(total_pnl)}
    print(f"S1 Kelly formula: p={p:.3f} b={b:+.4f} a={a:.4f} f*={f_f:+.4f}")
    print(f"S1 Kelly numeric : f*={f_n:.4f} on grid {f_grid_s1}")

    s1_rows = {}
    for f in [0.0, 0.01, 0.02, 0.03, 0.05, 0.10, 1.00]:
        m = simulate(w_real, f)
        s1_rows[f] = m
        print(f"  S1 f={f:5.2f}  {fmt(m)}")
    s1['mc'] = s1_rows
    scenarios['s1_real'] = s1

    s2 = {'label': 'Known-bugged W9 synthetic assumption (84-86% WR, iid +/-2%)'}
    s2['kelly_formula'] = {}
    for p_w in (0.84, 0.85, 0.86):
        b = 0.02
        a = 0.02
        f_star = p_w / a - (1 - p_w) / b
        s2['kelly_formula'][f'p={p_w}'] = {'b': float(b), 'a': float(a), 'f_star': float(f_star)}
        print(f"S2 Kelly formula p={p_w}: f*={f_star:.2f} (quarter {f_star/4:.2f})")

    w_syn = np.where(rng.random(10 * n) < 0.85, 0.02, -0.02)
    s2_f_vals = [0.0, 0.03, 1.00, 8.75, 35.0]
    s2['mc_fractions'] = s2_f_vals
    s2_rows = {}
    for f in s2_f_vals:
        m = simulate(w_syn, f, n_trades=n)
        s2_rows[f] = m
        print(f"  S2 f={f:5.2f}  {fmt(m)}")
    s2['mc'] = s2_rows
    scenarios['s2_bugged'] = s2

    report['scenarios'] = scenarios
    OUT.write_text(json.dumps(report, indent=2, default=float))
    print(f"\nSaved: {OUT}")

    print("\nCross-checks:")
    print(f"  S1 numeric f*={f_n:.4f} vs formula {f_f:+.4f} (<=0 -> Kelly says bet 0)")
    print("  S1 at f=1.00 (the bugged 100%-notional sizing): check MC -> trap visible")
    print(f"  S2 full Kelly 35x > discrete-loss limit 1/a=50x? {35.0 < 1/0.02}")


if __name__ == '__main__':
    main()
