#!/usr/bin/env python3
"""Walk-forward grid search on the KNOWN-BUGGED W9 synthetic distribution.

Diagnostic arm: same 108-config grid + same gates (G1-G4) as the real-data
search (walkforward_search.py), but trade streams are drawn iid from the W9
bugged-synthetic assumption (p=0.85 win at +2%, else -2%, 100%-notional PnL:
pnl_dollars = 100000.0 * pnl_pct — the bug that produced the 84-86% WR).

Purpose: quantify what the bugged synthetic data WOULD have told the search.
Expected: 108/108 configs pass trivially and identically (the synthetic stream
is parameter-independent -> zero discrimination between configs). This is the
diagnostic proof that selecting 'Deep' on synthetic walks was meaningless.

Binding gate: synthetic results carry NO implementation authority (W9 rule).
"""

import itertools
import json
from pathlib import Path

import numpy as np

OUT = Path('/home/nkhekhe/alpha_system/experiments/walkforward_results_synthetic_20260819.json')
REAL_RESULTS = Path('/home/nkhekhe/alpha_system/experiments/walkforward_results_20260819.json')

FOLDS = 4
K_GRID = [5, 10, 15, 20, 30, 40]
BARRIER_GRID = [0.01, 0.02, 0.03]
H_GRID = [10, 15, 30]
DIR_GRID = ['long', 'both']
P_WIN = 0.85
WIN = 0.02
LOSS = -0.02
SEED = 42

configs = []
for k, b, h, d in itertools.product(K_GRID, BARRIER_GRID, H_GRID, DIR_GRID):
    configs.append({'momentum_k': k, 'tp': b, 'sl': b, 'horizon': h, 'direction': d})
assert len(configs) == 108

real = json.loads(REAL_RESULTS.read_text())
fold_trades = [round(real['per_fold_totals'][str(f)]['n'] / 108) for f in range(FOLDS)]

rng = np.random.default_rng(SEED)


def synth_stream(n):
    signs = np.where(rng.random(n) < P_WIN, 1.0, -1.0)
    pnl_pct = signs * WIN if True else signs * LOSS
    pnl_pct = np.where(signs > 0, WIN, LOSS)
    pnl_dollars = 100000.0 * pnl_pct
    return pnl_pct, pnl_dollars


def main():
    cells = {}
    for ci in range(len(configs)):
        cells[ci] = {}
        for fi in range(FOLDS):
            pnl_pct, pnl_dollars = synth_stream(fold_trades[fi])
            n = len(pnl_pct)
            wins = int((pnl_dollars > 0).sum())
            cells[ci][fi] = {
                'n': n,
                'wr': wins / n,
                'net_pnl': float(pnl_dollars.sum()),
                'net_return_pct': float(pnl_dollars.sum() / 100000 * 100),
                'mean_w': float(pnl_pct.mean()),
            }

    rows = []
    for ci in range(len(configs)):
        g1 = all(cells[ci][fi]['n'] >= 20 for fi in range(FOLDS))
        g2 = sum(1 for fi in [0, 1, 2] if cells[ci][fi]['net_return_pct'] > 0) >= 2
        med = float(np.median([cells[ci][fi]['net_return_pct'] for fi in [0, 1, 2]]))
        rows.append({'config': configs[ci], 'g1': g1, 'g2': g2, 'train_median': med})
    passing = [r for r in rows if r['g1'] and r['g2']]
    selected = max(passing, key=lambda r: r['train_median']) if passing else None

    v = cells[0][3]
    g3 = v['net_return_pct'] > 0
    g4 = v['mean_w'] > 0.002
    verdict = 'PASS-synthetic' if (g3 and g4 and selected) else 'NO-GO'

    train_medians = [r['train_median'] for r in rows]
    out = {
        'arm': 'KNOWN-BUGGED W9 SYNTHETIC (diagnostic only, no implementation authority)',
        'p_win': P_WIN, 'win': WIN, 'loss': LOSS,
        'pnl_formula': 'pnl_dollars = 100000.0 * pnl_pct (100% notional, W9 bug)',
        'n_configs': len(configs),
        'fold_trades_per_config': fold_trades,
        'n_passing_train': len(passing),
        'train_median_std_across_configs': float(np.std(train_medians)),
        'train_median_min': float(min(train_medians)),
        'train_median_max': float(max(train_medians)),
        'selected': selected['config'] if selected else None,
        'selected_train_median': selected['train_median'] if selected else None,
        'validation_fold4': {'n': v['n'], 'wr': v['wr'],
                             'net_return_pct': v['net_return_pct'],
                             'mean_w': v['mean_w']},
        'gates': {'G1': True if passing else False, 'G2': True if passing else False,
                  'G3': g3, 'G4': g4},
        'verdict': verdict,
        'note': 'Synthetic stream is parameter-independent: all configs see the same '
                'trade distribution; parameter discrimination = 0 by construction.',
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(f"Synthetic arm: p_win={P_WIN}, +/-{WIN}, fold trades/config {fold_trades}")
    print(f"Configs passing G1+G2: {len(passing)} / 108")
    print(f"Train median across configs: min {out['train_median_min']:+.2f}% "
          f"max {out['train_median_max']:+.2f}% std {out['train_median_std_across_configs']:.4f}")
    print(f"Selected: {selected['config'] if selected else None} "
          f"(median {selected['train_median']:+.2f}%)")
    print(f"Validation fold4: n={v['n']} wr={v['wr']:.1%} "
          f"net={v['net_return_pct']:+.2f}% mean_w={v['mean_w']:+.4f}")
    print(f"G3={g3} G4={g4}")
    print(f">>> VERDICT: {verdict} <<<")
    print(f"Saved: {OUT}")


if __name__ == '__main__':
    main()