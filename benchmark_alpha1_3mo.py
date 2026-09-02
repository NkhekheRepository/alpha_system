#!/usr/bin/env python3
"""NK-EXP-W8-4 benchmark: Alpha 1 semantics on the SAME 3-month window (real data).

Alpha 1 live semantics (dry_runner): long-only unconditional churn,
momentum_k=0 (no signal gate), TP/SL 2%, H=15, 3% size, breaker 3->50, warmup 25.
Net of 0.1%/side fees. Plus buy-and-hold and the synthetic-doc reference.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_alpha2 as bt

DATA_DIR = Path('/home/nkhekhe/user_data/data/binance')
ASSETS = {'BTCUSDT': 'BTC_USDT-5m.feather', 'ETHUSDT': 'ETH_USDT-5m.feather'}
WINDOW_START = pd.Timestamp('2026-05-16 05:35:00+00:00')
WINDOW_END = pd.Timestamp('2026-08-16 05:35:00+00:00')
FEE = 0.001
CAP = 100000.0

ALPHA1_PARAMS = {
    'momentum_k': 0, 'tp': 0.02, 'sl': 0.02, 'horizon': 15,
    'pos_pct': 0.03, 'max_consec': 3, 'cooldown': 50, 'warmup': 25,
    'direction': 'long', 'k_sigma': None, 'vol_lookback': None, 'entry_z': 0.0,
}

def main():
    period_years = (WINDOW_END - WINDOW_START).total_seconds() / (365 * 24 * 3600)
    print("=" * 74)
    print(f"  BENCHMARK A — ALPHA 1 SEMANTICS (long-only churn) on 3-month window")
    print(f"  {WINDOW_START} -> {WINDOW_END}  ({period_years:.2f} y) | fee 0.1%/side")
    print("=" * 74)

    all_trades = []
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        df.attrs['symbol'] = sym
        df = df[(df['date'] >= WINDOW_START) & (df['date'] <= WINDOW_END)].reset_index(drop=True)
        trades, end_eq, max_dd = bt.run_strategy(df, capital=CAP, fees=FEE, params=ALPHA1_PARAMS)
        s = bt.summary(sym, trades, end_eq, period_years)
        s['max_dd'] = max_dd * 100
        bh, bh_ann = bt.buy_hold(df, period_years)
        print(f"\n  --- {sym} ---")
        print(f"  Trades: {s['trades']}  WR: {s['win_rate']:.1f}%  TP:{s['tp_hit_rate']:.1f}% SL:{s['sl_hit_rate']:.1f}% TO:{s['timeout_rate']:.1f}%")
        print(f"  Net PnL: ${s['net_pnl']:+,.0f} ({s['total_return_pct']:+.2f}%)  Sharpe {s['sharpe_ann']:.2f}  MaxDD {s['max_dd']:.2f}%")
        print(f"  Buy & Hold: {bh:+.2f}%")
        all_trades.extend(trades)

    all_trades.sort(key=lambda t: t['entry_time'])
    comb_eq = CAP + sum(t['pnl_dollars'] for t in all_trades)
    comb_ret = (comb_eq / CAP - 1) * 100
    comb_sharpe = bt.sharpe_from_trades(all_trades, period_years)
    n = len(all_trades)
    wins = sum(1 for t in all_trades if t['pnl_dollars'] > 0)
    print("\n" + "=" * 74)
    print(f"  COMBINED (BTC+ETH): {n} trades ({wins}W)  WR {wins/n*100 if n else 0:.1f}%")
    print(f"  Net PnL ${comb_eq-CAP:+,.0f} ({comb_ret:+.2f}%)  Sharpe {comb_sharpe:.2f}")
    print(f"  Ref (synthetic doc): 12 trades, 33.3% WR, 0.00% return")
    print("=" * 74)
    return {'return_pct': comb_ret, 'wr': wins / n * 100 if n else 0, 'trades': n}

if __name__ == '__main__':
    main()