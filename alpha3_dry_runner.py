#!/usr/bin/env python3
"""ALPHA 3 DRY MODE RUNNER - synthetic-resolution paper trading. SIMULATION ONLY.

Alpha 2 engine mechanics (BTC/ETH 60s polls, momentum-K10 direction, H15 hold,
circuit breaker 3 losses -> 50-bar cooldown) but every exit resolves via the
KNOWN-BUGGED W9 synthetic distribution: iid p=0.85 win +2% / p=0.15 loss -2%.
Staking matches Alpha 1/2 structure (fraction of current equity, compounding)
via --stake (default 0.3 = 30% per trade) on a 100 USDT synthetic base.

NOT A MARKET STRATEGY. No orders, no capital, no exchange wiring. Deployment
forbidden by protocol (PR-2026-08-19-ALPHA3-SYNTHETIC).
"""

import sys, os, json, csv, time, signal, argparse
from pathlib import Path
from datetime import datetime
import requests

sys.path.insert(0, '/home/nkhekhe')
sys.path.insert(0, '/home/nkhekhe/nkhekhe_quant_core')
sys.path.insert(0, '/home/nkhekhe/alpha_system')
from notify import send_message


def _notify(text):
    try:
        send_message(text, bot='alpha2')
    except Exception:
        pass


def check_daily_summary(state):
    now = datetime.utcnow()
    last = state.get('last_daily_summary')
    if last is None:
        state['last_daily_summary'] = now.isoformat()
        return False
    try:
        last_dt = datetime.fromisoformat(last)
        hours = (now - last_dt).total_seconds() / 3600
        if hours >= 24:
            state['last_daily_summary'] = now.isoformat()
            return True
    except Exception:
        pass
    return False

DATA_DIR = Path('/home/nkhekhe/alpha_system/dry_data')
STATE_FILE = DATA_DIR / 'alpha3_state.json'
TRADE_LOG = DATA_DIR / 'alpha3_trades.csv'
EQUITY_LOG = DATA_DIR / 'alpha3_equity.csv'

ASSETS = ['BTCUSDT', 'ETHUSDT']
API = 'https://api.binance.com/api/v3'
INTERVAL = 60

P_WIN = 0.85
WIN_PCT = 0.02
LOSS_PCT = -0.02
K = 10
H = 15
WARMUP = K + 5
MAX_CONSEC = 3
COOLDOWN = 50
CAP = 100.0
STAKE_PCT = 0.0025
LEVERAGE = 48.0


def default_state():
    return {
        'capital': CAP, 'equity': CAP, 'effective_equity': CAP,
        'peak_equity': CAP, 'max_drawdown': 0.0,
        'price_history': {}, 'open_positions': {}, 'trades': [],
        'daily_pnl': 0.0, 'consecutive_losses': 0, 'cooldown_remaining': 0,
        'total_trades': 0, 'total_wins': 0, 'total_losses': 0,
        'last_update': None, 'start_time': datetime.utcnow().isoformat(),
        'start_capital': CAP, 'stake_pct': None, 'leverage': None,
        'banner': 'SIMULATION ONLY - NOT A MARKET STRATEGY',
    }


def load_state(stake_pct, leverage):
    state = default_state()
    state['stake_pct'] = stake_pct
    state['leverage'] = leverage
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as fh:
                saved = json.load(fh)
            if saved.get('stake_pct') == stake_pct and saved.get('leverage') == leverage:
                state.update(saved)
            for _sym, _pos in state['open_positions'].items():
                if isinstance(_pos, dict) and 'age' not in _pos:
                    _pos['age'] = 0
        except Exception:
            pass
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return state


def save_state(state):
    state['last_update'] = datetime.utcnow().isoformat()
    with open(STATE_FILE, 'w') as fh:
        json.dump(state, fh, indent=2, default=str)


def log_trade(trade, state):
    new = not TRADE_LOG.exists()
    with open(TRADE_LOG, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['time', 'symbol', 'dir', 'entry', 'exit', 'resolve',
                        'pnl_pct', 'pnl_dollar', 'reason', 'equity', 'trades', 'wr'])
        w.writerow([trade['exit_time'], trade['symbol'], trade['direction'],
                    f"{trade['entry_price']:.2f}", f"{trade['exit_price']:.2f}",
                    trade['resolve'], f"{trade['pnl_pct']:.4f}",
                    f"{trade['pnl_dollars']:.2f}", trade['reason'],
                    f"{state['equity']:.2f}", state['total_trades'],
                    f"{100*state['total_wins']/state['total_trades']:.1f}"])


def log_equity(state):
    new = not EQUITY_LOG.exists()
    with open(EQUITY_LOG, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['time', 'equity', 'trades', 'wr', 'cooldown'])
        wr = 100*state['total_wins']/state['total_trades'] if state['total_trades'] else 0.0
        w.writerow([datetime.utcnow().isoformat(), f"{state['equity']:.2f}",
                    state['total_trades'], f"{wr:.1f}", state['cooldown_remaining']])


def get_price(symbol):
    try:
        r = requests.get(f"{API}/ticker/price", params={'symbol': symbol}, timeout=5)
        return float(r.json()['price'])
    except Exception:
        return None


def momentum_direction(ph):
    if len(ph) < K + 1:
        return None
    return 'long' if ph[-1] > ph[-1 - K] else 'short'


def run_cycle(state, rng):
    now = datetime.utcnow()
    ts = now.strftime('%H:%M:%S')

    if state['cooldown_remaining'] > 0:
        state['cooldown_remaining'] -= 1
        print(f"  [{ts}] Cooldown: {state['cooldown_remaining']} remaining")
        log_equity(state)
        return state

    prices = {}
    for s in ASSETS:
        p = get_price(s)
        if p is not None:
            prices[s] = p
    if not prices:
        print(f"  [{ts}] No prices, skip")
        return state

    for s in list(state['open_positions'].keys()):
        pos = state['open_positions'][s]
        pos['age'] += 1
        if pos['age'] < H:
            continue
        del state['open_positions'][s]
        win = rng.random() < P_WIN
        pct = WIN_PCT if win else LOSS_PCT
        exit_p = pos['entry_price'] * (1 + pct)
        pnl_d = pos['quantity'] * (exit_p - pos['entry_price'])
        state['equity'] += pnl_d
        state['peak_equity'] = max(state['peak_equity'], state['equity'])
        dd = (state['peak_equity'] - state['equity']) / state['peak_equity']
        state['max_drawdown'] = max(state['max_drawdown'], dd)
        state['total_trades'] += 1
        reason = 'SYNTH_WIN' if win else 'SYNTH_LOSS'
        if pnl_d > 0:
            state['total_wins'] += 1
            state['consecutive_losses'] = 0
        else:
            state['total_losses'] += 1
            state['consecutive_losses'] += 1
            if state['consecutive_losses'] >= MAX_CONSEC:
                state['cooldown_remaining'] = COOLDOWN
                state['consecutive_losses'] = 0
                print(f"  [{ts}] CIRCUIT BREAKER: {COOLDOWN}-bar cooldown")
                _notify(f"🛑 <b>CIRCUIT BREAKER — ALPHA 3 DRY</b>\n"
                        f"3 consecutive losses → {COOLDOWN}-bar cooldown\n"
                        f"Equity: ${state['equity']:,.2f}\n"
                        f"🛑 SIMULATION ONLY")
        trade = {
            'symbol': s, 'direction': pos['direction'],
            'entry_price': pos['entry_price'], 'exit_price': exit_p,
            'resolve': 'win' if win else 'loss', 'pnl_pct': pct,
            'pnl_dollars': pnl_d, 'reason': reason,
            'entry_time': pos['entry_time'],
            'exit_time': datetime.utcnow().isoformat(),
        }
        state['trades'].append(trade)
        log_trade(trade, state)
        print(f"  [{ts}] CLOSED {s} {pos['direction'].upper()}: {reason} | "
              f"PnL {pct:+.2%} (${pnl_d:+,.0f}) | Equity ${state['equity']:,.0f}")
        emoji = '🟢' if pnl_d > 0 else '🔴'
        _notify(f"{emoji} <b>CLOSED {s} {pos['direction'].upper()} — ALPHA 3 DRY</b>\n"
                f"Resolve: {'WIN' if win else 'LOSS'} (p=0.85 flip)\n"
                f"Entry: ${pos['entry_price']:,.2f} → Exit: ${exit_p:,.2f}\n"
                f"PnL: {pct:+.2%} (${pnl_d:+,.0f})\n"
                f"Equity: ${state['equity']:,.2f} | Trades: {state['total_trades']} "
                f"({state['total_wins']}W/{state['total_losses']}L)\n"
                f"🛑 SIMULATION ONLY")

    for s in ASSETS:
        if s not in state['open_positions'] and s in prices \
                and state['consecutive_losses'] < MAX_CONSEC:
            ph = state['price_history'].setdefault(s, [])
            ph.append(prices[s])
            if len(ph) > 200:
                state['price_history'][s] = ph[-200:]
            d = momentum_direction(state['price_history'][s])
            if d is not None and len(state['price_history'][s]) >= WARMUP:
                pos_val = state['capital'] * state['stake_pct'] * state['leverage']
                qty = pos_val / prices[s]
                state['open_positions'][s] = {
                    'symbol': s, 'direction': d,
                    'entry_price': prices[s], 'quantity': qty,
                    'notional': pos_val, 'age': 0,
                    'entry_time': datetime.utcnow().isoformat(),
                }
                print(f"  [{ts}] OPENED {s}: {d.upper()} @ ${prices[s]:,.2f} | "
                      f"stake ${pos_val:,.2f} (margin ${state['capital']*state['stake_pct']:,.2f} x {state['leverage']:g}x) "
                      f"| resolves in {H} bars")
                _notify(f"🎯 <b>OPENED {s} {d.upper()} — ALPHA 3 DRY</b>\n"
                        f"Entry: ${prices[s]:,.2f}\n"
                        f"Notional: ${pos_val:,.2f} (margin ${state['capital']*state['stake_pct']:,.2f} × {state['leverage']:g}x)\n"
                        f"Hold: {H} bars (~{H} min) → p=0.85 ±2% flip\n"
                        f"Equity: ${state['equity']:,.2f}\n"
                        f"🛑 SIMULATION ONLY")

    log_equity(state)
    if check_daily_summary(state):
        print(f"  [{ts}] DAILY SUMMARY SENT")
        wr = 100*state['total_wins']/state['total_trades'] if state['total_trades'] else 0.0
        base = state.get('start_capital', CAP)
        _notify(f"📊 <b>DAILY SUMMARY — ALPHA 3 DRY</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"💰 Equity: ${state['equity']:,.2f} (base ${base:,.0f})\n"
                f"PnL: ${state['equity']-base:+,.2f} ({(state['equity']-base)/base*100:+.2f}%)\n"
                f"Max DD: {state['max_drawdown']*100:.2f}%\n\n"
                f"📈 Trades: {state['total_trades']} "
                f"({state['total_wins']}W/{state['total_losses']}L, WR {wr:.1f}%)\n\n"
                f"⚡ Cooldown: {state['cooldown_remaining']} bars\n"
                f"🛑 SIMULATION ONLY")
    return state


def main():
    ap = argparse.ArgumentParser(description='Alpha 3 Dry Mode Runner (SIM ONLY)')
    ap.add_argument('--once', action='store_true', help='Single cycle')
    ap.add_argument('--status', action='store_true', help='Show status')
    ap.add_argument('--interval', type=int, default=INTERVAL, help='Poll seconds')
    ap.add_argument('--seed', type=int, default=1, help='RNG seed')
    ap.add_argument('--stake', type=float, default=STAKE_PCT,
                    help='Margin fraction of equity per trade')
    ap.add_argument('--leverage', type=float, default=LEVERAGE,
                    help='Leverage multiplier on margin')
    args = ap.parse_args()

    import numpy as np
    rng = np.random.default_rng(args.seed)

    if args.status:
        s = load_state(args.stake, args.leverage)
        wr = 100*s['total_wins']/s['total_trades'] if s['total_trades'] else 0.0
        print(f"Alpha3 DRY (SIM) stake={args.stake*100:g}% x {args.leverage:g}x | equity ${s['equity']:,.2f} | "
              f"trades {s['total_trades']} ({s['total_wins']}W/{s['total_losses']}L, WR {wr:.1f}%) | "
              f"open {list(s['open_positions'].keys())} | cooldown {s['cooldown_remaining']}")
        return

    state = load_state(args.stake, args.leverage)
    stake = state['capital'] * args.stake * args.leverage
    print("=" * 60)
    print("  ALPHA 3 DRY MODE RUNNER - SYNTHETIC RESOLUTION")
    print("  SIMULATION ONLY - NOT A MARKET STRATEGY - NO CAPITAL")
    print("=" * 60)
    print(f"  Assets:   BTC + ETH (60s polls)")
    print(f"  Engine:   momentum-K{K} direction, H={H} hold, CB {MAX_CONSEC}/{COOLDOWN}")
    print(f"  Resolve:  iid p={P_WIN} +/-2%")
    print(f"  Capital:  ${CAP:,.0f} USDT (synthetic)")
    print(f"  Staking:  {args.stake*100:g}% margin (${state['capital']*args.stake:,.2f}) x {args.leverage:g}x = ${stake:,.2f}/trade (compounding)")
    print(f"  Interval: {args.interval}s")
    print("=" * 60)
    sys.stdout.flush()

    running = True

    def handler(sig, frame):
        nonlocal running
        print("\n  Shutting down...")
        running = False
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    cycle = 0
    while running:
        cycle += 1
        try:
            state = run_cycle(state, rng)
            save_state(state)
            if args.once:
                print("  Single cycle done.")
                break
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  ERROR cycle {cycle}: {e}")
            time.sleep(30)
    save_state(state)
    print(f"  Stopped. Equity: ${state['equity']:,.2f} | Trades: {state['total_trades']}")


if __name__ == '__main__':
    main()
