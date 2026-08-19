#!/usr/bin/env python3
"""NK-EXP-W8-2: long-only momentum-10 evaluation (single hypothesis, no grid).
IS = first 80%, OOS = last 20% (same cutoff as NK-EXP-W8-1).
Gates from dry_data/alpha2_longonly_prereg.json. OOS consumed only if IS passes.
"""

import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/nkhekhe/alpha_system')
import backtest_alpha2 as bt
from search_alpha2 import fold_sharpe, barrier_hit_rate

DATA_DIR = Path('/home/nkhekhe/user_data/data/binance')
ASSETS = {'BTCUSDT': 'BTC_USDT-5m.feather', 'ETHUSDT': 'ETH_USDT-5m.feather'}
FEE = 0.001
CAP = 100000.0
PREREG = json.load(open('/home/nkhekhe/alpha_system/dry_data/alpha2_longonly_prereg.json'))
PARAMS = PREREG['fixed_params']

def load_split():
    full = {}
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        df.attrs['symbol'] = sym
        full[sym] = df
    cutoff = full['BTCUSDT']['date'].iloc[-1] - (full['BTCUSDT']['date'].iloc[-1] - full['BTCUSDT']['date'].iloc[0]) * 0.2
    is_data, oos_data = {}, {}
    for sym, df in full.items():
        mask = df['date'] < cutoff
        is_data[sym] = df[mask].reset_index(drop=True)
        oos_data[sym] = df[~mask].reset_index(drop=True)
    return is_data, oos_data, cutoff

def eval_split(data, label):
    all_trades = []
    for sym, df in data.items():
        trades, end_eq, dd = bt.run_strategy(df, capital=CAP, fees=FEE, params=PARAMS)
        all_trades.extend(trades)
        pnl = end_eq - CAP
        first, last = df['close'].iloc[0], df['close'].iloc[-1]
        bh = (last / first - 1) * 100
        print(f"    {sym}: {len(trades)} trades  PnL ${pnl:+,.0f} ({pnl/CAP*100:+.2f}%)  DD {dd*100:.1f}%  B&H {bh:+.2f}%")
    all_trades.sort(key=lambda t: t['entry_time'])
    n = len(all_trades)
    wins = sum(1 for t in all_trades if t['pnl_dollars'] > 0)
    folds = fold_sharpe(all_trades)
    pos_folds = sum(1 for s in folds if s > 0) / len(folds)
    total_pnl = sum(t['pnl_dollars'] for t in all_trades)
    print(f"    COMBINED ({label}): {n} trades  WR {wins/n*100 if n else 0:.1f}%  "
          f"barrier {barrier_hit_rate(all_trades)*100:.1f}%  PnL ${total_pnl:+,.0f} ({total_pnl/CAP*100:+.2f}%)")
    print(f"    Fold Sharpes: {[f'{s:+.2f}' for s in folds]}  median {np.median(folds):+.2f}  pos folds {pos_folds*100:.0f}%")
    return {'trades': n, 'wins': wins, 'folds': folds, 'median_sharpe': float(np.median(folds)),
            'pos_folds': pos_folds, 'barrier_hit_rate': barrier_hit_rate(all_trades),
            'net_pnl': total_pnl, 'net_return_pct': total_pnl / CAP * 100}

def main():
    print("=" * 78)
    print(f"  NK-EXP-W8-2 — ALPHA 2 LONG-ONLY (deployed params, single hypothesis)")
    print(f"  Params: k={PARAMS['momentum_k']} TP/SL={PARAMS['tp']} H={PARAMS['horizon']} "
          f"size={PARAMS['pos_pct']} brk={PARAMS['max_consec']} direction={PARAMS['direction']}")
    print("=" * 78)

    is_data, oos_data, cutoff = load_split()
    print(f"  Cutoff: {cutoff}")

    print("\n  --- IS (first 80%) ---")
    is_res = eval_split(is_data, "IS")

    # Also report bidirectional deployed config on IS for comparison (observation only)
    print("\n  --- IS reference: bidirectional deployed (observation, not selection) ---")
    bidir_params = dict(PARAMS); bidir_params['direction'] = 'both'
    for sym, df in is_data.items():
        trades, end_eq, dd = bt.run_strategy(df, capital=CAP, fees=FEE, params=bidir_params)
        pnl = end_eq - CAP
        print(f"    {sym}: {len(trades)} trades  PnL ${pnl:+,.0f} ({pnl/CAP*100:+.2f}%)")

    gates = PREREG['selection_gates']
    passed_is = (is_res['trades'] >= gates['min_trades']
                 and is_res['barrier_hit_rate'] >= gates['min_barrier_hit_rate']
                 and is_res['pos_folds'] >= gates['min_folds_positive_sharpe'])
    print(f"\n  IS GATES: trades>={gates['min_trades']} ({is_res['trades']}) | "
          f"barrier>={gates['min_barrier_hit_rate']*100:.0f}% ({is_res['barrier_hit_rate']*100:.1f}%) | "
          f"+Sharpe>={gates['min_folds_positive_sharpe']*100:.0f}% folds ({is_res['pos_folds']*100:.0f}%)")
    print(f"  >>> IS: {'PASS' if passed_is else 'FAIL'} <<<")

    if not passed_is:
        print("\n  >>> VERDICT: NO-GO at IS stage. OOS NOT consumed. Null recorded. <<<")
        with open('/home/nkhekhe/alpha_system/dry_data/alpha2_longonly_result.json', 'w') as f:
            json.dump({'registration': 'NK-EXP-W8-2', 'is': is_res, 'oos': None,
                       'verdict': 'NO-GO at IS stage', 'oos_consumed': False}, f, indent=2, default=str)
        return

    print("\n  --- OOS (last 20%, single evaluation) ---")
    oos_res = eval_split(oos_data, "OOS")

    ogates = PREREG['oos_gates']
    bh_pct = 0.0
    for sym, df in oos_data.items():
        bh_pct += (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100 / 2
    passed_oos = (oos_res['trades'] >= ogates['min_trades']
                  and oos_res['median_sharpe'] > ogates['net_sharpe_gt']
                  and oos_res['net_return_pct'] > bh_pct)
    print(f"\n  OOS GATES: trades>={ogates['min_trades']} ({oos_res['trades']}) | "
          f"net Sharpe>0 ({oos_res['median_sharpe']:+.2f}) | beats B&H ({oos_res['net_return_pct']:+.2f}% vs {bh_pct:+.2f}%)")
    verdict = 'GO' if passed_oos else 'NO-GO'
    print(f"  >>> VERDICT: {verdict} <<<")
    with open('/home/nkhekhe/alpha_system/dry_data/alpha2_longonly_result.json', 'w') as f:
        json.dump({'registration': 'NK-EXP-W8-2', 'is': is_res, 'oos': oos_res,
                   'verdict': verdict, 'oos_consumed': True}, f, indent=2, default=str)

if __name__ == '__main__':
    main()