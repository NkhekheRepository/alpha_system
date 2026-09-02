#!/usr/bin/env python3
"""ALPHA 3 - paper harness scaffold. SIMULATION ONLY - NOT A MARKET STRATEGY.

Per PR-2026-08-19-ALPHA3-SYNTHETIC (addendum 2026-08-24: barrier config aligned
to alpha_1percent.py TB_CONFIG for declarative parity): Alpha 3 resolves trades
via the known-bugged W9 synthetic distribution (p=0.85 +/-2%, pnl_dollars =
100000.0 * pnl_pct) with a dual real ledger. Real-ledger barriers are sourced
from alpha_3.TB_CONFIG (AlphaTripleBarrierConfig 2%/2% H=15 MAD-T flags),
byte-for-byte identical to alpha_1percent.py:74-83; effective barriers are fixed
±2% (core-library vol scaling is a stub; nkhekhe_quant_core/alpha_engine/labeling
__init__.py:71-75), SL stays 2% per user confirmation. 3% sizing for divergence.

DEPLOYMENT FORBIDDEN: no market orders, no capital, no live wiring. This harness
exists as an unstarted scaffold. To run an offline demo cycle: python3 alpha_3_runner.py --offline
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from alpha_3 import dual_run, synthetic_walk, summarize_real, summarize_synth

OUT = Path('/home/nkhekhe/alpha_system/dry_data/alpha3_state.json')


def main():
    ap = argparse.ArgumentParser(description='Alpha 3 simulator harness (NOT deployed)')
    ap.add_argument('--offline', action='store_true', help='run one offline demo cycle on saved feathers')
    ap.add_argument('--mode', type=float, default=0.03, choices=[0.03, 1.0, 8.75, 35.0],
                    help='synthetic sizing mode')
    args = ap.parse_args()

    # Banner includes config parity note so any later divergence is visible in logs.
    from alpha_3 import TB_CONFIG, ADDENDUM_HASH
    print("ALPHA 3 - SIMULATION ONLY. Not a market strategy. No orders, no capital.")
    print(f"  Barriers: TP {TB_CONFIG.upper_barrier:.0%} / SL {TB_CONFIG.lower_barrier:.0%} "
          f"H={TB_CONFIG.vertical_horizon} (TB_CONFIG parity with alpha_1percent.py)")
    print(f"  Addendum: {ADDENDUM_HASH}")
    if not args.offline:
        print("Scaffold only - invoke with --offline to run a demo cycle.")
        return

    import pandas as pd
    from backtest_alpha2 import ASSETS, DATA_DIR
    all_real = []
    all_synth = []
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        real, synth = dual_run(df['close'].to_numpy(), seed=1)
        all_real += real
        all_synth += synth
    rr = summarize_real(all_real)
    rs = summarize_synth(all_synth, args.mode)
    state = {'mode': args.mode, 'real': rr, 'synthetic': rs,
             'banner': 'SIMULATION ONLY - NOT A MARKET STRATEGY'}
    OUT.write_text(json.dumps(state, indent=2))
    print(f"real ledger : {rr['n']} trades, WR {rr['wr']:.1%}, net ${rr['net_pnl']:,.0f}")
    print(f"synth ledger: {rs['n']} trades, WR {rs['wr']:.1%}, net ${rs['net_pnl']:,.0f} "
          f"final ${rs['final_eq']:,.0f}")
    print(f"state -> {OUT}")


if __name__ == '__main__':
    main()