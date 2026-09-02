#!/usr/bin/env python3
"""
Dry Mode Runner - Live Paper Trading Simulator (Alpha 1%)
Continuously monitors Binance BTC + ETH via public API (60s polls).
Simulates trades with deployed parameters (TP=2%, SL=2%, H=75, 3% stake).
Logs all trades to CSV. No API keys needed. No real money.

Usage:
    python3 dry_runner.py              # Run continuously (60s interval)
    python3 dry_runner.py --once       # Single cycle (testing)
    python3 dry_runner.py --status     # Show current state
"""

import sys, os, json, csv, time, signal, argparse
from datetime import datetime
from pathlib import Path
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'nkhekhe_quant_core'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nkhekhe_quant_core.alpha_engine.labeling import AlphaTripleBarrierConfig, run_triple_barrier
from nkhekhe_quant_core.alpha_engine.risk import PositionSizingConfig, RiskGovernor
from notify import notify_trade_open, notify_trade_close, notify_circuit_breaker, notify_daily_summary, send_message
try:
    from audit import log_event
except Exception:
    log_event = lambda *a, **k: None  # no-op if audit unavailable

DATA_DIR = Path(__file__).resolve().parent / 'dry_data'
STATE_FILE = DATA_DIR / 'dry_state.json'
TRADE_LOG = DATA_DIR / 'dry_trades.csv'
EQUITY_LOG = DATA_DIR / 'dry_equity.csv'
CMD_FILE = DATA_DIR / 'alpha1_cmd.json'

TB = AlphaTripleBarrierConfig(upper_barrier=0.02, lower_barrier=0.02, vertical_horizon=75, direction='long')
RC = PositionSizingConfig(max_position_pct=0.03, max_daily_loss_pct=0.10, max_consecutive_losses=3, kelly_fraction=0.25, kelly_cap=0.5, stoploss_pct=0.15, max_signals_per_day=50)
COOLDOWN = 50
CAP = 100000.0
FEE_RATE = 0.0002  # 0.02% taker to match demo futures
INTERVAL = 60
ASSETS = ['BTCUSDT', 'ETHUSDT']
API = 'https://api.binance.com/api/v3'

def load_state():
    default = {
        'capital': CAP, 'equity': CAP, 'peak_equity': CAP,
        'effective_equity': CAP,
        'trades': [], 'open_positions': {},
        'price_history': {a: [] for a in ASSETS},
        'daily_pnl': 0.0, 'consecutive_losses': 0, 'cooldown_remaining': 0,
        'total_trades': 0, 'total_wins': 0, 'total_losses': 0,
        'max_drawdown': 0.0, 'last_update': None,
        'trading_enabled': True,
        'start_time': datetime.utcnow().isoformat(),
        'last_daily_summary': None,
    }
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            if 'effective_equity' not in state:
                state['effective_equity'] = state.get('capital', CAP)
            if not isinstance(state.get('open_positions'), dict):
                state['open_positions'] = {}
            for _sym, _pos in state['open_positions'].items():
                if isinstance(_pos, dict) and 'price_path' not in _pos:
                    _pos['price_path'] = [_pos.get('entry_price', 0.0)]
            return state
        except Exception:
            pass
    return default

def save_state(state):
    state['last_update'] = datetime.utcnow().isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)

def _notify(text):
    try:
        send_message(text, bot='alpha1')
    except Exception:
        pass

def check_commands(state):
    try:
        if CMD_FILE.exists():
            action = json.loads(CMD_FILE.read_text()).get('action')
            ts = datetime.utcnow().strftime('%H:%M:%S')
            if action == 'stop' and state.get('trading_enabled', True):
                state['trading_enabled'] = False
                print(f"  [{ts}] TRADING PAUSED via Telegram")
                _notify("\U0001F534 <b>TRADING PAUSED</b> - Alpha 1%: no new entries. Open positions still resolve.")
                try: log_event("alpha1", "trading_paused", {"via": "telegram"})
                except Exception: pass
            elif action == 'start' and not state.get('trading_enabled', True):
                state['trading_enabled'] = True
                print(f"  [{ts}] TRADING RESUMED via Telegram")
                _notify("\U0001F7E2 <b>TRADING RESUMED</b> - Alpha 1% active.")
                try: log_event("alpha1", "trading_resumed", {"via": "telegram"})
                except Exception: pass
            CMD_FILE.unlink()
    except Exception:
        pass

def get_price(symbol):
    try:
        r = requests.get(f"{API}/ticker/price", params={'symbol': symbol}, timeout=10)
        return float(r.json()['price'])
    except Exception as e:
        print(f"  ERROR: {symbol} price fetch failed: {e}")
        return None

def get_effective_equity(state, prices):
    """Capital + unrealized P&L from open positions."""
    cap = float(state.get('capital', CAP))
    unrealized = 0.0
    positions = state.get('open_positions')
    if not isinstance(positions, dict):
        return cap
    for sym, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        if sym not in prices:
            continue
        entry = pos.get('entry_price')
        qty = pos.get('quantity', 0)
        if entry is None or qty is None or qty <= 0:
            continue
        unrealized += (prices[sym] - float(entry)) * float(qty)
    return cap + unrealized

def log_trade(trade, state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    exists = TRADE_LOG.exists()
    with open(TRADE_LOG, 'a', newline='') as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(['time','symbol','dir','entry','exit','qty','pnl_pct','pnl_dollar','reason','equity','trades','wr','dd'])
        wr = state['total_wins']/state['total_trades']*100 if state['total_trades']>0 else 0
        dd = (state['peak_equity']-state['effective_equity'])/state['peak_equity'] if state['peak_equity']>0 else 0
        w.writerow([trade['exit_time'], trade['symbol'], trade['direction'],
                     f"{trade['entry_price']:.2f}", f"{trade['exit_price']:.2f}",
                     f"{trade['quantity']:.6f}", f"{trade['pnl_pct']:.4f}",
                     f"{trade['pnl_dollars']:.2f}", trade['reason'],
                     f"{state['equity']:.2f}", state['total_trades'], f"{wr:.1f}", f"{dd:.4f}"])

def log_equity(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    exists = EQUITY_LOG.exists()
    with open(EQUITY_LOG, 'a', newline='') as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(['time','equity','capital','dd','trades','wr'])
        wr = state['total_wins']/state['total_trades']*100 if state['total_trades']>0 else 0
        dd = (state['peak_equity']-state['effective_equity'])/state['peak_equity'] if state['peak_equity']>0 else 0
        w.writerow([datetime.utcnow().isoformat(), f"{state['equity']:.2f}",
                     f"{state['capital']:.2f}", f"{dd:.4f}", state['total_trades'], f"{wr:.1f}"])

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

def run_cycle(state):
    check_commands(state)
    now = datetime.utcnow()
    if state['total_trades'] > 0 and state['total_trades'] % 100 == 0:
        state['daily_pnl'] = 0.0
    if state['cooldown_remaining'] > 0:
        state['cooldown_remaining'] -= 1
        print(f"  [{now.strftime('%H:%M:%S')}] Cooldown: {state['cooldown_remaining']} remaining")
        return state
    if state['consecutive_losses'] >= RC.max_consecutive_losses:
        state['cooldown_remaining'] = COOLDOWN
        state['consecutive_losses'] = 0
        print(f"  [{now.strftime('%H:%M:%S')}] CIRCUIT BREAKER: {COOLDOWN}-bar cooldown")
        try:
            notify_circuit_breaker(state)
        except Exception:
            pass
        try: log_event("alpha1", "circuit_breaker", {"equity": round(state.get('equity', CAP),2), "cooldown": COOLDOWN, "trigger": "entry_guard"})
        except Exception: pass
        return state
    prices = {}
    for s in ASSETS:
        p = get_price(s)
        if p is not None:
            prices[s] = p
    if not prices:
        print(f"  [{now.strftime('%H:%M:%S')}] No prices, skip")
        return state
    for s in list(state['open_positions'].keys()):
        if s in prices:
            pos = state['open_positions'][s]
            if not isinstance(pos, dict):
                continue
            path = pos.setdefault('price_path', [pos['entry_price']])
            path.append(prices[s])
            if len(path) > 200:
                pos['price_path'] = path[-200:]
            entry = pos['entry_price']
            tp = pos['tp_price']
            sl = pos['sl_price']
            direction = pos.get('direction', 'long')
            last = path[-1]
            close_reason = None
            exit_p = None
            if direction == 'long':
                if last >= tp:
                    close_reason, exit_p = 'TP', tp
                elif last <= sl:
                    close_reason, exit_p = 'SL', sl
                elif len(path) >= TB.vertical_horizon + 1:
                    close_reason, exit_p = 'TIMEOUT', last
            else:
                if last <= tp:
                    close_reason, exit_p = 'TP', tp
                elif last >= sl:
                    close_reason, exit_p = 'SL', sl
                elif len(path) >= TB.vertical_horizon + 1:
                    close_reason, exit_p = 'TIMEOUT', last
            if close_reason is not None:
                state['open_positions'].pop(s)
                if direction == 'short':
                    pnl_d = pos['quantity'] * (entry - exit_p)
                else:
                    pnl_d = pos['quantity'] * (exit_p - entry)
                fee = pos['quantity'] * (entry + exit_p) * FEE_RATE
                pnl_d -= fee
                if direction == 'short':
                    pnl_pct = pnl_d / (pos['quantity'] * entry) if entry and pos['quantity'] else 0.0
                else:
                    pnl_pct = pnl_d / (pos['quantity'] * entry) if entry and pos['quantity'] else 0.0
                state['capital'] += pnl_d
                state['equity'] = state['capital']
                state['effective_equity'] = state['capital']
                state['peak_equity'] = max(state['peak_equity'], state['equity'])
                dd = (state['peak_equity']-state['equity'])/state['peak_equity']
                state['max_drawdown'] = max(state['max_drawdown'], dd)
                state['total_trades'] += 1
                if pnl_d > 0:
                    state['total_wins'] += 1
                    state['consecutive_losses'] = 0
                else:
                    state['total_losses'] += 1
                    state['consecutive_losses'] += 1
                    if state['consecutive_losses'] >= RC.max_consecutive_losses:
                        state['cooldown_remaining'] = COOLDOWN
                        state['consecutive_losses'] = 0
                        print(f"  [{now.strftime('%H:%M:%S')}] CIRCUIT BREAKER: {COOLDOWN}-bar cooldown")
                        try:
                            notify_circuit_breaker(state)
                        except Exception:
                            pass
                        try: log_event("alpha1", "circuit_breaker", {"equity": round(state.get('equity', CAP),2), "cooldown": COOLDOWN})
                        except Exception: pass
                trade = {
                    'symbol': s, 'direction': direction,
                    'entry_price': entry, 'exit_price': exit_p,
                    'quantity': pos['quantity'], 'pnl_pct': pnl_pct,
                    'pnl_dollars': pnl_d, 'reason': close_reason,
                    'entry_time': pos['entry_time'],
                    'exit_time': datetime.utcnow().isoformat()
                }
                state['trades'].append(trade)
                log_trade(trade, state)
                print(f"  [{now.strftime('%H:%M:%S')}] CLOSED {s} {direction.upper()}: {close_reason} @ ${exit_p:,.2f} | PnL {pnl_pct:+.2%} (${pnl_d:+,.0f}) | Equity ${state['equity']:,.0f}")
                try:
                    notify_trade_close(trade, state)
                except Exception:
                    pass
                try: log_event("alpha1", "trade_close", {"symbol": s, "direction": direction, "reason": close_reason, "pnl_pct": round(pnl_pct,6), "pnl_dollars": round(pnl_d,2), "equity": round(state['equity'],2)})
                except Exception: pass
    for s in ASSETS:
        if s not in state['open_positions'] and s in prices \
                and state['cooldown_remaining'] == 0 \
                and state['consecutive_losses'] < RC.max_consecutive_losses:
            ph = state['price_history'].setdefault(s, [])
            ph.append(prices[s])
            if len(ph) > 200:
                state['price_history'][s] = ph[-200:]
            if state.get('trading_enabled', True) and len(state['price_history'][s]) >= TB.vertical_horizon + 10:
                pos_val = state['capital'] * RC.max_position_pct
                qty = pos_val / prices[s]
                state['open_positions'][s] = {
                    'symbol': s, 'direction': 'long',
                    'entry_price': prices[s], 'quantity': qty,
                    'entry_time': datetime.utcnow().isoformat(),
                    'tp_price': prices[s] * 1.02, 'sl_price': prices[s] * 0.98,
                    'price_path': [prices[s]]
                }
                print(f"  [{now.strftime('%H:%M:%S')}] OPENED {s}: LONG @ ${prices[s]:,.2f} | TP ${prices[s]*1.02:,.2f} | SL ${prices[s]*0.98:,.2f}")
                try:
                    trade_info = {
                        'symbol': s, 'direction': 'long',
                        'entry_price': prices[s], 'quantity': qty,
                        'tp_price': prices[s] * 1.02, 'sl_price': prices[s] * 0.98
                    }
                    notify_trade_open(trade_info, state)
                except Exception:
                    pass
                try: log_event("alpha1", "trade_open", {"symbol": s, "direction": "long", "entry": round(prices[s],2), "qty": round(qty,6)})
                except Exception: pass
    effective = get_effective_equity(state, prices)
    state['effective_equity'] = effective
    state['peak_equity'] = max(state['peak_equity'], effective)
    log_equity(state)
    if check_daily_summary(state):
        print(f"  [{now.strftime('%H:%M:%S')}] DAILY SUMMARY SENT")
        try:
            notify_daily_summary(state)
        except Exception:
            pass
        try:
            wr = 100*state['total_wins']/state['total_trades'] if state['total_trades'] else 0.0
            log_event("alpha1", "daily_summary", {"equity": round(state['equity'],2), "trades": state['total_trades'], "wr": round(wr,1)})
        except Exception: pass
    if state['total_trades'] > 0 and state['total_trades'] % 10 == 0:
        wr = state['total_wins']/state['total_trades']*100
        dd = (state['peak_equity']-state['effective_equity'])/state['peak_equity']*100
        print(f"  [{now.strftime('%H:%M:%S')}] STATUS: Trades={state['total_trades']} WR={wr:.1f}% PnL=${state['equity']-CAP:+,.0f} DD={dd:.1f}%")
    return state

def show_status():
    if not STATE_FILE.exists():
        print("  No dry mode state found. Start with: python3 dry_runner.py")
        return
    s = load_state()
    prices = {}
    for sym in ASSETS:
        p = get_price(sym)
        if p is not None:
            prices[sym] = p
    effective = get_effective_equity(s, prices)
    peak = float(s.get('peak_equity', CAP))
    dd = (peak - effective) / peak * 100 if peak > 0 else 0
    print("="*70)
    print("  DRY MODE STATUS")
    print(f"  Trading: {'ON' if s.get('trading_enabled', True) else 'PAUSED'}")
    print("="*70)
    print(f"  Started:     {s.get('start_time','N/A')}")
    print(f"  Last update: {s.get('last_update','N/A')}")
    t = s['total_trades']; w = s['total_wins']; l = s['total_losses']
    wr = w/t*100 if t else 0; pnl = s['equity']-CAP
    unrealized = effective - s['capital']
    print(f"  Equity:      ${s['equity']:,.2f}")
    print(f"  Realized:    ${pnl:+,.2f}")
    print(f"  Unrealized:  ${unrealized:+,.2f}")
    print(f"  Total P&L:   ${effective-CAP:+,.2f} ({dd:.2f}%)")
    print(f"  Max DD:      {dd:.2f}%")
    print(f"  Trades:      {t} ({w}W/{l}L)")
    print(f"  Win rate:    {wr:.1f}%")
    print(f"  Cooldown:    {s['cooldown_remaining']}")
    positions = s.get('open_positions')
    if isinstance(positions, dict) and positions:
        print("\n  OPEN POSITIONS:")
        for sym, pos in positions.items():
            if isinstance(pos, dict):
                ep = prices.get(sym, pos.get('entry_price', 0))
                entry = pos.get('entry_price', 0)
                qty = pos.get('quantity', 0)
                upnl = (ep - entry) * qty
                print(f"    {sym}: LONG @ ${entry:,.2f} | Now ${ep:,.2f} | PnL ${upnl:+,.2f}")
    else:
        print("\n  No open positions")
    if s.get('trades'):
        print("\n  LAST 5 TRADES:")
        for t in s['trades'][-5:]:
            if isinstance(t, dict):
                print(f"    {t.get('symbol','?')}: {t.get('reason','?')} @ ${t.get('exit_price',0):,.2f} | PnL {t.get('pnl_pct',0):+.2%} (${t.get('pnl_dollars',0):+,.0f})")
    print("\n  LOGS:")
    print(f"    {TRADE_LOG}")
    print(f"    {EQUITY_LOG}")
    print("="*70)

def main():
    parser = argparse.ArgumentParser(description='Dry Mode Runner')
    parser.add_argument('--once', action='store_true', help='Single cycle')
    parser.add_argument('--status', action='store_true', help='Show status')
    parser.add_argument('--interval', type=int, default=INTERVAL, help='Poll seconds')
    args = parser.parse_args()
    if args.status:
        show_status()
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    print("="*70)
    print("  DRY MODE RUNNER - LIVE PAPER TRADING SIMULATOR")
    print("="*70)
    print(f"  Assets:   BTC + ETH")
    print(f"  Params:   TP=2% | SL=2% | H=75")
    print(f"  Capital:  ${CAP:,.0f}")
    print(f"  Interval: {args.interval}s")
    print(f"  Binance:  MAINNET (https://api.binance.com)")
    print()
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
            state = run_cycle(state)
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
