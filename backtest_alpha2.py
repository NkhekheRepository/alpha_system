#!/usr/bin/env python3
"""
Backtest for Alpha 2% (Bidirectional) strategy.
Causal event-driven simulation on 5m Binance data (BTC + ETH).

Strategy (matches bidir_runner.py as deployed):
  - Direction: momentum-10 sign (close[T]/close[T-10] - 1 > 0 -> LONG, < 0 -> SHORT)
  - Entry: at close of bar T when flat and >= 25 bars of history
  - Exits: first close in T+1..T+15 crossing +2% TP or -2% SL (flipped for short);
           vertical timeout at T+15 -> exit at close[T+15]
  - Sizing: 3% of capital per position
  - Circuit breaker: 3 consecutive losses -> 50-bar cooldown
  - Fees: 0.1% taker per side on notional (entry + exit)
  - Capital: 100,000; one position per symbol at a time; equity = realized capital

No lookahead: signal at bar T uses only closes <= T; exits use closes > T.
No parameter search. Outputs gross and net-of-fee results + buy-and-hold baselines.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

DATA_DIR = Path('/home/nkhekhe/user_data/data/binance')
ASSETS = {'BTCUSDT': 'BTC_USDT-5m.feather', 'ETHUSDT': 'ETH_USDT-5m.feather'}

CAP = 100000.0
POS_PCT = 0.03
TP = 0.02
SL = 0.02
HORIZON = 15
WARMUP_BARS = 25
MOMENTUM_K = 10
MAX_CONSEC_LOSSES = 3
COOLDOWN = 50
FEE = 0.001  # 0.1% taker per side

BARS_PER_YEAR = (365 * 24 * 60) / 5  # 105,120 5m bars/year


def momentum_direction(closes, k=MOMENTUM_K):
    if len(closes) < k + 1:
        return None
    ret = closes[-1] / closes[-1 - k] - 1
    if ret > 0:
        return 'long'
    elif ret < 0:
        return 'short'
    return None


def run_strategy(df, capital=CAP, fees=FEE, params=None):
    """Simulate Alpha 2 on one symbol. Returns trades list + equity + max_dd.

    params overrides strategy constants (for search):
      momentum_k, tp, sl, horizon, pos_pct, max_consec, cooldown, warmup,
      direction ('both'|'long'|'short'),
      k_sigma, vol_lookback, entry_z  (vol-scaled barrier mode)
    """
    p = {
        'momentum_k': MOMENTUM_K, 'tp': TP, 'sl': SL, 'horizon': HORIZON,
        'pos_pct': POS_PCT, 'max_consec': MAX_CONSEC_LOSSES,
        'cooldown': COOLDOWN, 'warmup': WARMUP_BARS, 'direction': 'both',
        'k_sigma': None, 'vol_lookback': None, 'entry_z': 0.0,
    }
    if params:
        p.update(params)
    k = p['momentum_k']; tp = p['tp']; sl = p['sl']; H = p['horizon']
    pos_pct = p['pos_pct']; max_consec = p['max_consec']
    cooldown_bars = p['cooldown']; warmup = p['warmup']
    direction_filter = p['direction']  # 'both' | 'long' | 'short'
    k_sigma = p['k_sigma']; vol_lookback = p['vol_lookback']
    entry_z = p['entry_z']
    vol_scaled = k_sigma is not None and vol_lookback is not None

    closes = df['close'].to_numpy()
    times = df['date'].to_numpy()
    n = len(closes)

    # Precompute rolling std of 5m log returns (vol[t] = std over bars [t-N, t-1])
    vol = None
    if vol_scaled:
        logc = np.log(np.maximum(closes, 1e-9))
        rets = np.diff(logc)
        s = pd.Series(rets).rolling(vol_lookback, min_periods=vol_lookback).std(ddof=1).to_numpy()
        vol = np.full(n, np.nan)
        vol[1:] = s

    trades = []
    equity = capital
    peak = capital
    max_dd = 0.0
    consec_losses = 0
    cooldown = 0
    position = None  # {'dir','entry','qty','tp','sl','entry_bar','entry_ts'}

    for t in range(n):
        # ---- manage cooldown (decrement each bar) ----
        if cooldown > 0:
            cooldown -= 1

        # ---- exit check: close-based barrier over next bars ----
        if position is not None:
            d = position['dir']
            # Barrier scan: from entry_bar+1 up to entry_bar+HORIZON
            if t > position['entry_bar'] and t <= position['entry_bar'] + H:
                c = closes[t]
                if d == 'long':
                    if c >= position['tp']:
                        exit_p, reason = position['tp'], 'TP'
                    elif c <= position['sl']:
                        exit_p, reason = position['sl'], 'SL'
                    else:
                        exit_p, reason = None, None
                else:
                    if c <= position['tp']:
                        exit_p, reason = position['tp'], 'TP'
                    elif c >= position['sl']:
                        exit_p, reason = position['sl'], 'SL'
                    else:
                        exit_p, reason = None, None
            elif t > position['entry_bar'] + H:
                exit_p, reason = closes[position['entry_bar'] + H], 'TIMEOUT'
            else:
                exit_p, reason = None, None

            if exit_p is not None:
                if d == 'long':
                    pnl_pct = (exit_p - position['entry']) / position['entry']
                else:
                    pnl_pct = (position['entry'] - exit_p) / position['entry']
                notional = position['qty'] * position['entry']
                fee_cost = notional * fees + position['qty'] * exit_p * fees
                fee_cost = notional * fees + position['qty'] * exit_p * fees
                pnl_d = position['qty'] * (exit_p - position['entry']) if d == 'long' \
                    else position['qty'] * (position['entry'] - exit_p)
                pnl_d = pnl_d - fee_cost
                pnl_pct = pnl_d / notional  # net of fees
                equity += pnl_d
                if pnl_d > 0:
                    consec_losses = 0
                else:
                    consec_losses += 1
                    if consec_losses >= max_consec:
                        cooldown = cooldown_bars
                        consec_losses = 0
                trades.append({
                    'symbol': df.attrs.get('symbol', '?'),
                    'direction': d, 'reason': reason,
                    'entry_time': str(position['entry_ts']),
                    'exit_time': str(times[t]),
                    'entry_price': position['entry'],
                    'exit_price': exit_p,
                    'quantity': position['qty'],
                    'pnl_pct': pnl_pct,
                    'pnl_dollars': pnl_d,
                    'hold_bars': t - position['entry_bar'],
                })
                position = None

        # ---- entry check ----
        if position is None and cooldown == 0 and t >= warmup:
            if vol_scaled:
                v = vol[t]
                if np.isnan(v) or v <= 0:
                    d = None
                else:
                    # vol-normalized momentum filter: |ret_k| / (vol * sqrt(k)) >= z
                    if t >= k:
                        ret_k = closes[t] / closes[t - k] - 1
                        z = abs(ret_k) / (v * np.sqrt(k))
                        if z < entry_z:
                            d = None
                        else:
                            d = 'long' if ret_k > 0 else 'short' if ret_k < 0 else None
                    else:
                        d = None
            else:
                if k <= 0:
                    d = 'long'  # no-signal churn mode (Alpha 1 live semantics)
                else:
                    d = momentum_direction(closes[:t + 1], k=k)
            if direction_filter == 'long' and d == 'short':
                d = None
            elif direction_filter == 'short' and d == 'long':
                d = None
            if d is not None:
                entry = closes[t]
                qty = (equity * pos_pct) / entry
                if vol_scaled:
                    width = k_sigma * v * np.sqrt(H)
                else:
                    width = tp
                position = {
                    'dir': d, 'entry': entry, 'qty': qty,
                    'tp': entry * (1 - width) if d == 'short' else entry * (1 + width),
                    'sl': entry * (1 + width) if d == 'short' else entry * (1 - width),
                    'entry_bar': t, 'entry_ts': times[t],
                }

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    # Force-close any open position at last bar
    if position is not None:
        last_p = closes[n - 1]
        d = position['dir']
        pnl_d = position['qty'] * (last_p - position['entry']) if d == 'long' \
            else position['qty'] * (position['entry'] - last_p)
        notional = position['qty'] * position['entry']
        pnl_d -= notional * fees + position['qty'] * last_p * fees
        pnl_pct = pnl_d / notional
        equity += pnl_d
        trades.append({
            'symbol': df.attrs.get('symbol', '?'),
            'direction': d, 'reason': 'END',
            'entry_time': str(position['entry_ts']),
            'exit_time': str(times[n - 1]),
            'entry_price': position['entry'],
            'exit_price': last_p,
            'quantity': position['qty'],
            'pnl_pct': (last_p - position['entry']) / position['entry'] if d == 'long'
                       else (position['entry'] - last_p) / position['entry'],
            'pnl_dollars': pnl_d,
            'hold_bars': n - 1 - position['entry_bar'],
        })
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    return trades, equity, max_dd


def sharpe_from_trades(trades, period_years):
    if len(trades) < 2 or period_years <= 0:
        return 0.0
    rets = np.array([t['pnl_pct'] for t in trades])
    mu = rets.mean()
    sd = rets.std(ddof=1)
    if sd == 0:
        return 0.0
    n_per_year = len(trades) / period_years
    return (mu / sd) * np.sqrt(n_per_year)


def summary(name, trades, end_eq, period_years):
    n = len(trades)
    wins = [t for t in trades if t['pnl_dollars'] > 0]
    losses = [t for t in trades if t['pnl_dollars'] <= 0]
    tp_hits = [t for t in trades if t['reason'] == 'TP']
    sl_hits = [t for t in trades if t['reason'] == 'SL']
    timeouts = [t for t in trades if t['reason'] == 'TIMEOUT']
    total_ret = (end_eq / CAP - 1) * 100
    net = sum(t['pnl_dollars'] for t in trades)
    gross = net + sum(0.0 for _ in trades)  # fees already embedded; report net
    hold = np.mean([t['hold_bars'] for t in trades]) if n else 0
    long_trades = [t for t in trades if t['direction'] == 'long']
    short_trades = [t for t in trades if t['direction'] == 'short']
    sharpe = sharpe_from_trades(trades, period_years)
    return {
        'name': name, 'trades': n,
        'wins': len(wins), 'losses': len(losses),
        'win_rate': len(wins) / n * 100 if n else 0,
        'tp_hit_rate': len(tp_hits) / n * 100 if n else 0,
        'sl_hit_rate': len(sl_hits) / n * 100 if n else 0,
        'timeout_rate': len(timeouts) / n * 100 if n else 0,
        'total_return_pct': total_ret,
        'net_pnl': net,
        'avg_hold_bars': hold,
        'sharpe_ann': sharpe,
        'long': len(long_trades), 'short': len(short_trades),
        'long_wr': len([t for t in long_trades if t['pnl_dollars'] > 0]) / len(long_trades) * 100 if long_trades else 0,
        'short_wr': len([t for t in short_trades if t['pnl_dollars'] > 0]) / len(short_trades) * 100 if short_trades else 0,
        'avg_win': np.mean([t['pnl_dollars'] for t in wins]) if wins else 0,
        'avg_loss': np.mean([t['pnl_dollars'] for t in losses]) if losses else 0,
    }


def buy_hold(df, period_years):
    first = df['close'].iloc[0]
    last = df['close'].iloc[-1]
    ret = (last / first - 1) * 100
    ann = ((last / first) ** (1 / period_years) - 1) * 100 if period_years > 0 else 0
    return ret, ann


def main():
    period_years = None
    all_trades = []
    results = []

    print("=" * 74)
    print("  ALPHA 2% BACKTEST — Bidirectional Momentum (TP/SL 2%, H=15)")
    print("  Fee: 0.1%/side taker | Sizing: 3% | Breaker: 3L -> 50 bars")
    print("=" * 74)

    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        df.attrs['symbol'] = sym
        if period_years is None:
            t0 = pd.Timestamp(df['date'].iloc[0])
            t1 = pd.Timestamp(df['date'].iloc[-1])
            period_years = (t1 - t0).total_seconds() / (365 * 24 * 3600)
            print(f"\n  Window: {t0} -> {t1}  ({period_years:.2f} years, {len(df):,} bars)")

        trades, end_eq, max_dd = run_strategy(df)
        s = summary(sym, trades, end_eq, period_years)
        s['max_dd'] = max_dd * 100
        results.append(s)
        all_trades.extend(trades)

        bh_ret, bh_ann = buy_hold(df, period_years)
        print(f"\n  --- {sym} ---")
        print(f"  Trades: {s['trades']} ({s['long']}L / {s['short']}S)  WR: {s['win_rate']:.1f}%")
        print(f"    TP hit: {s['tp_hit_rate']:.1f}% | SL hit: {s['sl_hit_rate']:.1f}% | Timeout: {s['timeout_rate']:.1f}%")
        print(f"    Long WR: {s['long_wr']:.1f}%  |  Short WR: {s['short_wr']:.1f}%")
        print(f"  Avg hold: {s['avg_hold_bars']:.1f} bars ({s['avg_hold_bars']*5/60:.1f}h)")
        print(f"  Net PnL: ${s['net_pnl']:+,.0f}  ({s['total_return_pct']:+.2f}%)")
        print(f"  Annualized Sharpe: {s['sharpe_ann']:.2f}")
        print(f"  Max Drawdown: {s['max_dd']:.2f}%")
        print(f"  Avg win: ${s['avg_win']:+,.0f} | Avg loss: ${s['avg_loss']:+,.0f}")
        print(f"  Buy & Hold: {bh_ret:+.2f}% total ({bh_ann:+.2f}%/yr)")

    # Portfolio: combine both symbols' trades sequentially on shared capital
    all_trades.sort(key=lambda t: t['entry_time'])
    comb_eq = CAP
    for t in all_trades:
        comb_eq += t['pnl_dollars']
    comb_ret = (comb_eq / CAP - 1) * 100
    comb_sharpe = sharpe_from_trades(all_trades, period_years)
    wins = sum(1 for t in all_trades if t['pnl_dollars'] > 0)
    n = len(all_trades)
    print("\n" + "=" * 74)
    print("  COMBINED (BTC + ETH, shared capital)")
    print(f"  Trades: {n} ({wins}W / {n-wins}L)  WR: {wins/n*100 if n else 0:.1f}%")
    print(f"  Net PnL: ${comb_eq-CAP:+,.0f}  ({comb_ret:+.2f}%)")
    print(f"  Annualized Sharpe (trade-serialized): {comb_sharpe:.2f}")
    print(f"  Period: {period_years:.2f} years")

    # Verdict
    print("\n" + "=" * 74)
    print("  VERDICT (net of fees)")
    n_long = sum(1 for t in all_trades if t['direction'] == 'long')
    n_short = sum(1 for t in all_trades if t['direction'] == 'short')
    ok_freq = n >= 20
    ok_sharpe = comb_sharpe > 0
    ok_bh = any(r['total_return_pct'] > 0 for r in results)
    print(f"  Trades >= 20:            {'PASS' if ok_freq else 'FAIL'} ({n})")
    print(f"  Net Sharpe > 0:          {'PASS' if ok_sharpe else 'FAIL'} ({comb_sharpe:.2f})")
    print(f"  Direction coverage:      {n_long} LONG / {n_short} SHORT")
    verdict = 'GO' if (ok_freq and ok_sharpe) else 'NO-GO'
    print(f"  >>> VERDICT: {verdict} <<<")
    print("=" * 74)


if __name__ == '__main__':
    main()
