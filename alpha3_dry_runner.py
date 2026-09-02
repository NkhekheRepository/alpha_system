#!/usr/bin/env python3
"""ALPHA 3 DRY MODE RUNNER - triple-barrier paper (testnet spot, 5m cadence).

Engine: Alpha 3 / Alpha 1% clone — 7 assets (ALPHA3_ASSETS, 5m polls),
momentum-K10 direction, H=15 hold (75 min wall-clock), TP 3.5% / SL 2% market
barriers every poll, TIMEOUT at bar 15. Circuit breaker 3 losses -> 50-bar
cooldown. Staking: 3% equity per trade (POS_PCT=0.03, compounding, no leverage)
on a 100 USDT synthetic base; barriers sourced from TB_CONFIG (alpha_1percent
parity: 2%/2%, vol flags). Matches alpha_3.py simulation energy & frequency
(5m candles, 50-min momentum window). Telegram bot is the main remote control
(state -> alpha3_live_state.json, commands <- alpha3_cmd.json).

Credibility: real-market resolution only — no synthetic flip.
Exchange: testnet spot (testnet.binance.vision/api/v3) when BINANCE_USE_TESTNET=true.
"""

import sys, os, json, csv, time, signal, argparse, tempfile
from pathlib import Path
from datetime import datetime
import requests
import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'nkhekhe_quant_core'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import send_message
try:
    from audit import log_event
except Exception:
    log_event = lambda *a, **k: None  # no-op if audit unavailable

DEMO_LIVE = os.environ.get('BINANCE_DEMO_LIVE', 'true').lower() in ('1','true','yes','on')
_DEMO_IMPORT_ERR = None
if DEMO_LIVE:
    try:
        from demo_trader import place_market_order, place_limit_order, set_leverage_all, set_leverage
    except Exception as e:
        import traceback as _tb
        _DEMO_IMPORT_ERR = f"{e}\n{_tb.format_exc()}"
        DEMO_LIVE = False


def _notify(text):
    try:
        send_message(text, bot='alpha2')
    except Exception:
        pass


def check_commands(state):
    try:
        # External one-way kill trigger (flag file created by any process / human)
        if KILL_FILE.exists() and not state.get('kill_armed', False):
            engage_kill_switch(state)
        if CMD_FILE.exists():
            action = json.loads(CMD_FILE.read_text()).get('action')
            ts = datetime.utcnow().strftime('%H:%M:%S')
            if action == 'stop' and state.get('trading_enabled', True):
                state['trading_enabled'] = False
                print(f"  [{ts}] TRADING PAUSED via Telegram")
                _notify("\U0001F534 <b>TRADING PAUSED</b> - Alpha 3%: no new entries. Open positions still resolve.")
                try: log_event("alpha3", "trading_paused", {"via": "telegram"})
                except Exception: pass
            elif action == 'start' and not state.get('trading_enabled', True):
                state['trading_enabled'] = True
                print(f"  [{ts}] TRADING RESUMED via Telegram")
                _notify("\U0001F7E2 <b>TRADING RESUMED</b> - Alpha 3% active.")
                try: log_event("alpha3", "trading_resumed", {"via": "telegram"})
                except Exception: pass
            elif action == 'kill' and not state.get('kill_armed', False):
                engage_kill_switch(state)
            elif action == 'disarm' and state.get('kill_armed', False):
                disarm_kill_switch(state)
            CMD_FILE.unlink()
    except Exception:
        pass


def _flatten_positions(state):
    """Close ALL open positions, booking each as a realized trade.

    Shared by the human kill switch and graceful shutdown. Does NOT arm the kill
    switch and resets the circuit-breaker counters — a deliberate human close (or
    a shutdown) must not be punished by an extra cooldown. Returns
    (closed, kill_pnl, symbols).
    """
    closed = 0
    kill_pnl = 0.0
    symbols = []
    for s in list(state.get('open_positions', {}).keys()):
        pos = state['open_positions'][s]
        direction = pos.get('direction', 'long')
        entry = pos.get('entry_price', 0.0)
        qty = pos.get('quantity', 0.0)
        try:
            exit_p = get_price(s) or entry
        except Exception:
            exit_p = entry
        if direction == 'long':
            pct = (exit_p - entry) / entry if entry else 0.0
            pnl_d = qty * (exit_p - entry)
        else:
            pct = (entry - exit_p) / entry if entry else 0.0
            pnl_d = qty * (entry - exit_p)
        fee = qty * (entry + exit_p) * FEE_RATE
        pnl_d -= fee
        kill_pnl += pnl_d
        state['capital'] += pnl_d
        state['equity'] = state['capital']
        state['total_trades'] += 1
        if pnl_d > 0:
            state['total_wins'] += 1
        else:
            state['total_losses'] += 1
        trade = {
            'symbol': s, 'direction': direction,
            'entry_price': entry, 'exit_price': exit_p,
            'resolve': 'market', 'pnl_pct': pct,
            'pnl_dollars': pnl_d, 'reason': 'KILL',
            'entry_time': pos.get('entry_time'),
            'exit_time': datetime.utcnow().isoformat(),
        }
        state['trades'].append(trade)
        log_trade(trade, state)
        if DEMO_LIVE:
            try:
                from demo_trader import cancel_algo_orders, place_market_order
                cancel_algo_orders(s)
                side = 'SELL' if direction == 'long' else 'BUY'
                place_market_order(s, side, qty, reduce_only=True)
            except Exception as e:
                _notify(f"⚠️ Kill close {s} failed: {e}")
        del state['open_positions'][s]
        closed += 1
        symbols.append(s)
        _notify(f"{'🟢' if pnl_d > 0 else '🔴'} <b>KILL CLOSE {s} {direction.upper()}</b> "
                f"PnL {pct:+.2%} (${pnl_d:+,.2f})")
    state['peak_equity'] = max(state.get('peak_equity', state['equity']), state['equity'])
    dd = (state['peak_equity'] - state['equity']) / state['peak_equity'] if state['peak_equity'] else 0.0
    state['max_drawdown'] = max(state.get('max_drawdown', 0.0), dd)
    # A human kill / shutdown is a deliberate reset: clear the circuit breaker so
    # trading can resume cleanly afterward (do not double-penalize the operator).
    state['consecutive_losses'] = 0
    state['cooldown_remaining'] = 0
    return closed, kill_pnl, symbols


def engage_kill_switch(state):
    """HUMAN-IN-THE-LOOP kill: close ALL open positions exactly once, then COOL.

    Each closed position is BOOKED (PnL realized into equity + trade log) and the
    aggregate kill PnL / metrics are written to the kill ledger. The runner keeps
    running (monitoring / status) but opens no new trades until /disarm.
    """
    ts = datetime.utcnow().strftime('%H:%M:%S')
    equity_before = float(state.get('equity', state.get('capital', CAP)))
    closed, kill_pnl, symbols = _flatten_positions(state)
    state['kill_armed'] = True
    state['trading_enabled'] = False
    equity_after = float(state.get('equity', state['capital']))
    _write_kill_ledger(state, equity_before, equity_after, kill_pnl, closed, symbols)
    if closed:
        _notify(f"🛑 <b>KILL SWITCH ENGAGED</b> — Alpha 3%: {closed} position(s) CLOSED (once), "
                f"kill PnL ${kill_pnl:+,.2f}. Runner in COOL. Send /disarm to re-arm.")
    else:
        _notify(f"🛑 <b>KILL SWITCH ENGAGED</b> — Alpha 3%: no open positions. Runner in COOL.")
    print(f"  [{ts}] KILL SWITCH ENGAGED — {closed} closed, kill PnL ${kill_pnl:+,.2f}, runner COOL")
    try: log_event("alpha3", "kill_switch_engaged", {"closed": closed, "kill_pnl": round(kill_pnl, 2), "equity_after": round(equity_after, 2)})
    except Exception: pass


def _write_kill_ledger(state, equity_before, equity_after, kill_pnl, closed, symbols):
    """Persist every kill engagement: PnL captured, metrics, context."""
    new = not KILL_LOG.exists()
    with open(KILL_LOG, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['time', 'equity_before', 'equity_after', 'kill_pnl_total',
                        'n_closed', 'symbols', 'best_return_pct', 'worst_drawdown_pct',
                        'total_trades', 'win_rate'])
        wr = 100 * state['total_wins'] / state['total_trades'] if state['total_trades'] else 0.0
        w.writerow([datetime.utcnow().isoformat(), f"{equity_before:.2f}", f"{equity_after:.2f}",
                    f"{kill_pnl:.2f}", closed, "|".join(symbols),
                    f"{state.get('best_return_pct', 0.0) * 100:.2f}",
                    f"{state.get('worst_drawdown_pct', 0.0) * 100:.2f}",
                    state['total_trades'], f"{wr:.1f}"])


def disarm_kill_switch(state):
    """Re-arm after a human kill: clear the cool flag and resume trading."""
    state['kill_armed'] = False
    state['trading_enabled'] = True
    _notify("🟢 <b>KILL SWITCH DISARMED</b> — Alpha 3% trading re-enabled.")
    print(f"  KILL SWITCH DISARMED — trading re-enabled")
    try: log_event("alpha3", "kill_switch_disarmed", {})
    except Exception: pass


def _track_best_worst(state, effective):
    """Machine-in-the-loop visibility: track peak return and worst drawdown."""
    base = state.get('start_capital', CAP) or CAP
    ret = (effective - base) / base if base else 0.0
    state['best_return_pct'] = max(state.get('best_return_pct', 0.0), ret)
    peak = state.get('peak_equity', effective) or effective
    dd = (peak - effective) / peak if peak else 0.0
    state['worst_drawdown_pct'] = max(state.get('worst_drawdown_pct', 0.0), dd)


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

DATA_DIR = Path(__file__).resolve().parent / 'dry_data'
STATE_FILE = DATA_DIR / 'alpha3_state.json'
TRADE_LOG = DATA_DIR / 'alpha3_trades.csv'
EQUITY_LOG = DATA_DIR / 'alpha3_equity.csv'
CMD_FILE = DATA_DIR / 'alpha3_cmd.json'
KILL_FILE = DATA_DIR / 'alpha3_kill.flag'
KILL_LOG = DATA_DIR / 'alpha3_kill_log.csv'
FLATTEN_ON_SHUTDOWN = True  # systemctl stop / SIGTERM flattens all open positions

from binance_config import BINANCE_API_BASE, ALPHA3_ASSETS, ALPHA3_GROUP, USE_LIVE
# Trading mode switch: testnet (default) or live
TRADING_MODE = os.getenv("TRADING_MODE", "testnet").lower()
if TRADING_MODE == "live":
    BINANCE_FAPI_BASE = "https://fapi.binance.com"
else:
    BINANCE_FAPI_BASE = "https://testnet.binancefuture.com"
ASSETS = ALPHA3_ASSETS
API = BINANCE_API_BASE
INTERVAL = 60

K = 30
H = 100
WARMUP = H + 10
MAX_CONSEC = 3
COOLDOWN = 50
CAP = 10.0
STAKE_PCT = 0.20
LEVERAGE = 20.0
# Per-symbol leverage overrides. Demo futures rejects some symbols at high leverage
# (e.g. BICOUSDT rejects 20x -> ERROR 400). Those symbols are capped here; all others
# use --leverage.
LEV_OVERRIDE = {'BICOUSDT': 10.0}
FEE_RATE = 0.0002  # 0.02% taker fee to match demo futures
WIN_PCT = 0.035
LOSS_PCT = -0.02

# Meta-labeler config
META_LABELER_PATH = Path(__file__).resolve().parent / 'models/meta_labeler.joblib'
META_THRESHOLD = 0.50  # from training

# Orderbook cache for microstructure features
_orderbook_cache = {}  # {symbol: {'bookTicker': {...}, 'depth': [...], 'ts': timestamp}}

def get_orderbook(symbol):
    """Fetch orderbook + bookTicker for symbol. Returns dict or None."""
    global _orderbook_cache
    now = time.time()
    # Return cached if fresh (< 60s)
    cached = _orderbook_cache.get(symbol)
    if cached and now - cached['ts'] < 60:
        return cached
    try:
        # Fetch bookTicker (top of book)
        r1 = requests.get(f"{API}/ticker/bookTicker", params={'symbol': symbol}, timeout=5)
        if r1.status_code != 200:
            return None
        bt = r1.json()
        # Fetch depth (top 20 levels)
        r2 = requests.get(f"{API}/depth", params={'symbol': symbol, 'limit': 20}, timeout=5)
        if r2.status_code != 200:
            return None
        depth = r2.json()
        ob = {'bookTicker': bt, 'depth': depth, 'ts': time.time()}
        _orderbook_cache[symbol] = ob
        return ob
    except Exception:
        return None


def load_meta_labeler():
    """Load frozen meta-labeler model."""
    try:
        model_data = joblib.load(META_LABELER_PATH)
        return model_data['model'], model_data.get('threshold', META_THRESHOLD)
    except Exception as e:
        print(f"  [meta-labeler] Failed to load: {e}")
        return None, META_THRESHOLD


# Feature computation for meta-labeler (must match training exactly)
def _rolling_mean(x, w):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.insert(x, 0, 0))
    out[w-1:] = (cs[w:] - cs[:-w]) / w
    return out


def _rolling_std(x, w):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(x)
    cs2 = np.cumsum(x**2)
    for i in range(w-1, len(x)):
        s = cs[i] - (cs[i-w] if i >= w else 0)
        s2 = cs2[i] - (cs2[i-w] if i >= w else 0)
        mean = s / w
        var = s2 / w - mean**2
        out[i] = np.sqrt(max(var, 0))
    return out


def _ema(x, span):
    alpha = 2 / (span + 1)
    ema = np.full(len(x), np.nan)
    ema[0] = x[0]
    for i in range(1, len(x)):
        ema[i] = alpha * x[i] + (1 - alpha) * ema[i-1]
    return ema


def compute_meta_features(closes, highs, lows, volumes, idx, ob_history=None):
    """Compute all 36 features at bar index idx (no look-ahead)."""
    n = len(closes)
    if idx < 199 or idx >= n:
        return None
    c = closes[idx-199:idx+1]
    h = highs[idx-199:idx+1]
    l = lows[idx-199:idx+1]
    v = volumes[idx-199:idx+1]
    i = 199

    feat = {}

    # Momentum
    for w in [5, 10, 20, 50]:
        feat[f'ret_{w}'] = (c[i] - c[i-w]) / c[i-w]

    # RSI
    for period in [7, 14]:
        deltas = np.diff(c[i-period:i+1])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = _ema(gains, period)[-1]
        avg_loss = _ema(losses, period)[-1]
        rs = avg_gain / (avg_loss + 1e-10)
        feat[f'rsi_{period}'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    feat['macd'] = macd_line[-1] / c[-1]
    feat['macd_signal'] = signal_line[-1] / c[-1]
    feat['macd_hist'] = (macd_line[-1] - signal_line[-1]) / c[-1]

    # Volatility
    for w in [10, 20, 50]:
        feat[f'vol_{w}'] = np.std(c[i-w+1:i+1]) / c[i]

    # ATR (14)
    tr = np.zeros(len(c))
    tr[1:] = np.maximum(h[1:] - l[1:],
                         np.maximum(np.abs(h[1:] - c[:-1]),
                                    np.abs(l[1:] - c[:-1])))
    atr = _rolling_mean(tr, 14)[-1]
    feat['atr_14'] = atr / c[-1]

    # BB
    ma20 = np.mean(c[-20:])
    std20 = np.std(c[-20:])
    if std20 > 0 and ma20 > 0:
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        feat['bb_pos'] = (c[-1] - lower) / (upper - lower)
        feat['bb_width'] = (upper - lower) / ma20
    else:
        feat['bb_pos'] = 0.5
        feat['bb_width'] = 0

    # Range/close pos
    hl = h[-1] - l[-1]
    feat['range_ratio'] = hl / c[-1] if c[-1] > 0 else 0
    feat['close_position'] = (c[-1] - l[-1]) / hl if hl > 0 else 0.5

    # Volume
    for w in [10, 20, 50]:
        ma = np.mean(v[-w:])
        feat[f'vol_ratio_{w}'] = v[-1] / ma if ma > 0 else 1
    ma50 = np.mean(v[-50:])
    feat['vol_spike'] = v[-1] / ma50 if ma50 > 0 else 1

    # Regime
    for w in [20, 50, 100, 200]:
        ma = np.mean(c[-w:])
        feat[f'price_vs_ma{w}'] = (c[-1] - ma) / ma if ma > 0 else 0

    # MA crosses
    ma20v = np.mean(c[-20:])
    ma50v = np.mean(c[-50:])
    ma100v = np.mean(c[-100:])
    feat['ma50_ma20_cross'] = (ma20v - ma50v) / ma50v if ma50v > 0 else 0
    feat['ma100_ma50_cross'] = (ma50v - ma100v) / ma100v if ma100v > 0 else 0

    # Trend slope
    ma50_vals = [np.mean(c[j-50:j]) for j in range(len(c)-20, len(c))]
    if len(ma50_vals) > 1 and ma50_vals[0] > 0:
        feat['trend_slope'] = (ma50_vals[-1] - ma50_vals[0]) / ma50_vals[0]
    else:
        feat['trend_slope'] = 0

    # Microstructure
    consec = 0
    if i > 0:
        sign = np.sign(c[i] - c[i-1])
        for j in range(i, max(0, i-20), -1):
            if j > 0 and np.sign(c[j] - c[j-1]) == sign:
                consec += 1
            else:
                break
        feat['consec_direction'] = consec * sign
    else:
        feat['consec_direction'] = 0

    feat['hh_streak_5'] = sum(1 for j in range(i-4, i+1) if h[j] > h[j-1])
    feat['ll_streak_5'] = sum(1 for j in range(i-4, i+1) if l[j] < l[j-1])

    d1 = c[-1] - c[-6]
    d2 = c[-6] - c[-11]
    feat['momentum_accel'] = (d1 - d2) / c[-1]

    # Time
    feat['hour_sin'] = np.sin(2 * np.pi * (idx % 1440) / 1440)
    feat['hour_cos'] = np.cos(2 * np.pi * (idx % 1440) / 1440)
    feat['dow_sin'] = np.sin(2 * np.pi * ((idx // 1440) % 7) / 7)
    feat['dow_cos'] = np.cos(2 * np.pi * ((idx // 1440) % 7) / 7)

    return feat


FEATURE_ORDER = [
    'ret_5', 'ret_10', 'ret_20', 'ret_50',
    'rsi_7', 'rsi_14',
    'macd', 'macd_signal', 'macd_hist',
    'vol_10', 'vol_20', 'vol_50',
    'atr_14', 'bb_pos', 'bb_width',
    'range_ratio', 'close_position',
    'vol_ratio_10', 'vol_ratio_20', 'vol_ratio_50', 'vol_spike',
    'price_vs_ma20', 'price_vs_ma50', 'price_vs_ma100', 'price_vs_ma200',
    'ma50_ma20_cross', 'ma100_ma50_cross', 'trend_slope',
    'consec_direction', 'hh_streak_5', 'll_streak_5', 'momentum_accel',
    'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
]


def features_to_array(feat_dict):
    if feat_dict is None:
        return None
    return np.array([feat_dict.get(f, np.nan) for f in FEATURE_ORDER], dtype=np.float32).reshape(1, -1)


def default_state():
    return {
        'capital': CAP, 'equity': CAP, 'effective_equity': CAP,
        'peak_equity': CAP, 'max_drawdown': 0.0,
        'price_history': {}, 'open_positions': {}, 'trades': [],
        'daily_pnl': 0.0, 'consecutive_losses': 0, 'cooldown_remaining': 0,
        'total_trades': 0, 'total_wins': 0, 'total_losses': 0,
        'last_update': None, 'start_time': datetime.utcnow().isoformat(),
        'trading_enabled': True,
        'kill_armed': False,
        'best_return_pct': 0.0,
        'worst_drawdown_pct': 0.0,
        'start_capital': CAP, 'stake_pct': None, 'leverage': None,
        'banner': '',
    }


def load_state(stake_pct, leverage):
    state = default_state()
    state['stake_pct'] = stake_pct
    state['leverage'] = leverage
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as fh:
                saved = json.load(fh)
            # DONT reset DB on stake change — migrate preserves equity/trades
            if saved.get('stake_pct') == stake_pct and saved.get('leverage') == leverage:
                state.update(saved)
            else:
                # migrate: keep all DB fields, only update stake/leverage
                print(f"  [migrate] stake {saved.get('stake_pct')}->{stake_pct} lev {saved.get('leverage')}->{leverage} — preserving DB ({saved.get('total_trades',0)}t, ${saved.get('equity',0):.2f})")
                state.update(saved)
                state['stake_pct'] = stake_pct
                state['leverage'] = leverage
                try: log_event("alpha3", "stake_migrated", {"old_stake": saved.get('stake_pct'), "new_stake": stake_pct, "old_lev": saved.get('leverage'), "new_lev": leverage, "equity": round(saved.get('equity',0),2), "trades": saved.get('total_trades',0)})
                except Exception: pass
            if abs(state['capital'] - state['equity']) > 1e-9:
                state['capital'] = state['equity']
            for _sym, _pos in state['open_positions'].items():
                if isinstance(_pos, dict) and 'age' not in _pos:
                    _pos['age'] = 0
            # Backfill kill-switch visibility from historical peak/drawdown
            _base = state.get('start_capital', CAP) or CAP
            _peak = state.get('peak_equity', state.get('equity', CAP)) or CAP
            _best = (state.get('best_return_pct', 0.0)
                     if isinstance(state.get('best_return_pct'), (int, float)) else 0.0)
            state['best_return_pct'] = max(_best, (_peak - _base) / _base if _base else 0.0)
            _worst = (state.get('worst_drawdown_pct', 0.0)
                      if isinstance(state.get('worst_drawdown_pct'), (int, float)) else 0.0)
            state['worst_drawdown_pct'] = max(_worst, state.get('max_drawdown', 0.0))
        except Exception as e:
            print(f"  [load_state warn] {e}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return state


def save_state(state):
    state['last_update'] = datetime.utcnow().isoformat()
    # Atomic write: write to a temp file in the same directory then os.replace.
    # Previously this truncated the state file in place, so a crash mid-write
    # (or the bot/reconciler reading during truncate) saw a truncated/corrupt
    # JSON and load_state hard-failed, silently resetting the trading DB.
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), prefix='.alpha3_state.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(state, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def get_effective_equity(state, prices):
    """Capital + unrealized P&L from open positions (mirrors Alpha 1)."""
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


def log_equity(state):
    new = not EQUITY_LOG.exists()
    with open(EQUITY_LOG, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['time', 'equity', 'effective_equity', 'trades', 'wr', 'cooldown'])
        wr = 100*state['total_wins']/state['total_trades'] if state['total_trades'] else 0.0
        eff = state.get('effective_equity', state['equity'])
        w.writerow([datetime.utcnow().isoformat(), f"{state['equity']:.2f}", f"{eff:.2f}",
                    state['total_trades'], f"{wr:.1f}", state['cooldown_remaining']])


def get_ohlcv(symbol):
    """Fetch latest 1m kline for OHLCV data."""
    try:
        r = requests.get(f"{API}/klines", params={'symbol': symbol, 'interval': '1m', 'limit': 1}, timeout=5)
        data = r.json()
        if data:
            k = data[0]
            return {
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'close_time': k[6],
            }
    except Exception:
        pass
    return None


def get_price(symbol):
    """Backward compatibility — return close price."""
    ohlcv = get_ohlcv(symbol)
    return ohlcv['close'] if ohlcv else None


def momentum_direction(ph):
    """ph is list of OHLCV dicts or close prices."""
    if len(ph) < K + 1:
        return None
    # Extract close prices
    closes = [c['close'] if isinstance(c, dict) else c for c in ph]
    return 'long' if closes[-1] > closes[-1 - K] else 'short'


def run_cycle(state, meta_model=None, meta_threshold=META_THRESHOLD):
    check_commands(state)
    now = datetime.utcnow()
    ts = now.strftime('%H:%M:%S')

    # KILL SWITCH (human-in-the-loop): if armed, flatten stragglers, take no new
    # trades, but keep the runner alive/monitoring with refreshed equity.
    if state.get('kill_armed', False):
        if state.get('open_positions'):
            engage_kill_switch(state)
        ohlcv_data = {}
        for s in ASSETS:
            o = get_ohlcv(s)
            if o is not None:
                ohlcv_data[s] = o
        prices = {s: o['close'] for s, o in ohlcv_data.items()}
        eff = get_effective_equity(state, prices)
        state['effective_equity'] = eff
        state['peak_equity'] = max(state.get('peak_equity', eff), eff)
        _track_best_worst(state, eff)
        log_equity(state)
        return state

    ohlcv_data = {}
    orderbook_data = {}
    for s in ASSETS:
        o = get_ohlcv(s)
        if o is not None:
            ohlcv_data[s] = o
        ob = get_orderbook(s)
        if ob is not None:
            orderbook_data[s] = ob
    if not ohlcv_data:
        print(f"  [{ts}] No OHLCV data, skip")
        return state

    # Extract close prices for backward compatibility
    prices = {s: o['close'] for s, o in ohlcv_data.items()}

    # Bootstrap OHLCV history if price_history has < 200 bars (need 200 for features)
    for s in ASSETS:
        ph = state['price_history'].get(s, [])
        if len(ph) < 200:
            print(f"  [{ts}] BOOTSTRAP START {s} ({len(ph)} bars)...")
            try:
                r = requests.get(f"{API}/klines", params={'symbol': s, 'interval': '1m', 'limit': 201}, timeout=10)
                klines = r.json()
                new_ph = []
                for k in klines:
                    new_ph.append({
                        'open': float(k[1]),
                        'high': float(k[2]),
                        'low': float(k[3]),
                        'close': float(k[4]),
                        'volume': float(k[5]),
                        'close_time': k[6],
                    })
                state['price_history'][s] = new_ph[-201:]
                print(f"  [{ts}] BOOTSTRAP DONE {s} ({len(new_ph)} bars)")
            except Exception as e:
                print(f"  [{ts}] BOOTSTRAP FAIL {s}: {e}")

    # Continuous OHLCV history — momentum stays fresh even with open positions
    for s in ASSETS:
        if s in ohlcv_data:
            ph = state['price_history'].setdefault(s, [])
            ct = ohlcv_data[s].get('close_time')
            # Dedup: the API returns the in-progress (not-yet-closed) 1m bar
            # repeatedly, and the runner may poll more than once within the same
            # 1m bucket. Never append a bar whose close_time is already present;
            # replace the last bar in place instead (it is the same bucket).
            if ph and ph[-1].get('close_time') == ct:
                ph[-1] = ohlcv_data[s]
            else:
                ph.append(ohlcv_data[s])
            if len(ph) > 200:
                state['price_history'][s] = ph[-200:]

    # Continuous orderbook history — for microstructure features
    for s in ASSETS:
        if s in orderbook_data:
            ob_hist = state.setdefault('orderbook_history', {}).setdefault(s, [])
            ob_hist.append(orderbook_data[s])
            if len(ob_hist) > 200:
                ob_hist[:] = ob_hist[-200:]

    # Exit evaluation ALWAYS runs, even during cooldown (cooldown gates entries only)
    for s in list(state['open_positions'].keys()):
        pos = state['open_positions'][s]
        # Wall-clock age: robust to failed polls / cooldown cycles
        try:
            wc_age = int((now - datetime.fromisoformat(pos['entry_time'])).total_seconds() // INTERVAL)
        except Exception:
            wc_age = pos.get('age', 0)
        pos['age'] = max(pos.get('age', 0), wc_age)
        if s not in prices:
            continue
        # Back-compat: flip-era positions lack tp/sl
        if 'tp_price' not in pos:
            pos['tp_price'] = pos['entry_price'] * (0.965 if pos['direction'] == 'short' else 1.035)
            pos['sl_price'] = pos['entry_price'] * (1.02 if pos['direction'] == 'short' else 0.98)
        direction = pos['direction']
        entry = pos['entry_price']
        tp = pos['tp_price']
        sl = pos['sl_price']
        last = prices[s]
        close_reason = None
        exit_p = None
        resolve = None
        pct = None
        if direction == 'long':
            if last >= tp:
                close_reason, exit_p, resolve, pct = 'TP', tp, 'market', (tp - entry) / entry
            elif last <= sl:
                close_reason, exit_p, resolve, pct = 'SL', sl, 'market', (sl - entry) / entry
        else:
            if last <= tp:
                close_reason, exit_p, resolve, pct = 'TP', tp, 'market', (entry - tp) / entry
            elif last >= sl:
                close_reason, exit_p, resolve, pct = 'SL', sl, 'market', (entry - sl) / entry
        if close_reason is None:
            if pos['age'] < H:
                continue
            close_reason, exit_p, resolve = 'TIMEOUT', last, 'market'
            pct = ((exit_p - entry) / entry if direction == 'long' else (entry - exit_p) / entry)
        del state['open_positions'][s]
        pnl_d = pos['quantity'] * ((exit_p - entry) if direction == 'long'
                                   else (entry - exit_p))
        fee = pos['quantity'] * (entry + exit_p) * FEE_RATE
        pnl_d -= fee
        pct = pnl_d / (pos['quantity'] * entry) if entry and pos['quantity'] else 0.0
        state['capital'] += pnl_d
        state['equity'] = state['capital']
        state['peak_equity'] = max(state['peak_equity'], state['equity'])
        dd = (state['peak_equity'] - state['equity']) / state['peak_equity']
        state['max_drawdown'] = max(state['max_drawdown'], dd)
        state['total_trades'] += 1
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
                        f"Equity: ${state['equity']:,.2f}")
                try: log_event("alpha3", "circuit_breaker", {"equity": round(state['equity'],2), "cooldown": COOLDOWN})
                except Exception: pass
        trade = {
            'symbol': s, 'direction': direction,
            'entry_price': entry, 'exit_price': exit_p,
            'resolve': resolve, 'pnl_pct': pct,
            'pnl_dollars': pnl_d, 'reason': close_reason,
            'entry_time': pos['entry_time'],
            'exit_time': datetime.utcnow().isoformat(),
        }
        state['trades'].append(trade)
        log_trade(trade, state)
        print(f"  [{ts}] CLOSED {s} {direction.upper()}: {close_reason} | "
              f"PnL {pct:+.2%} (${pnl_d:+,.2f}) | Equity ${state['equity']:,.2f}")
        emoji = '🟢' if pnl_d > 0 else '🔴'
        how = f"{close_reason} (market) at bar {pos['age']}"
        _notify(f"{emoji} <b>CLOSED {s} {direction.upper()} — ALPHA 3 DRY</b>\n"
                f"Exit: {how}\n"
                f"Entry: ${entry:,.2f} → Exit: ${exit_p:,.2f}\n"
                f"PnL: {pct:+.2%} (${pnl_d:+,.2f})\n"
                f"Equity: ${state['equity']:,.2f} | Trades: {state['total_trades']} "
                f"({state['total_wins']}W/{state['total_losses']}L)")
        try: log_event("alpha3", "trade_close", {"symbol": s, "direction": direction, "reason": close_reason, "pnl_pct": round(pct,6), "pnl_dollars": round(pnl_d,2), "equity": round(state['equity'],2)})
        except Exception: pass
        if DEMO_LIVE and close_reason in ('TP','SL','TIMEOUT'):
            try:
                from demo_trader import cancel_algo_orders
                cancel_algo_orders(s)
            except Exception:
                pass
            try:
                side = 'SELL' if direction == 'long' else 'BUY'
                order, err = place_market_order(s, side, pos['quantity'], reduce_only=True)
                if order:
                    _notify(f"📡 Demo close {s}: {side} {pos['quantity']:.6f} filled")
                elif err:
                    _notify(f"⚠️ Demo close {s} failed: {err}")
            except Exception as e:
                _notify(f"⚠️ Demo close {s} exception: {e}")

    # Cooldown gates NEW ENTRIES only — exits were already evaluated above
    if state['cooldown_remaining'] > 0:
        state['cooldown_remaining'] -= 1
        print(f"  [{ts}] Cooldown: {state['cooldown_remaining']} remaining")

    for s in ASSETS:
        if s not in state['open_positions'] and s in prices \
                and state['cooldown_remaining'] == 0:
            d = momentum_direction(state['price_history'][s])
            if state.get('trading_enabled', True) and not state.get('kill_armed', False) and d is not None and len(state['price_history'][s]) >= WARMUP:
                # Meta-labeler filter
                if meta_model is not None:
                    ph = state['price_history'][s]
                    idx = len(ph) - 1
                    # Extract OHLCV arrays
                    closes = np.array([c['close'] for c in ph])
                    highs = np.array([c['high'] for c in ph])
                    lows = np.array([c['low'] for c in ph])
                    volumes = np.array([c['volume'] for c in ph])
                    # Get orderbook history for this symbol (if available)
                    ob_history = state.get('orderbook_history', {}).get(s, [])
                    feat = compute_meta_features(closes, highs, lows, volumes, idx, ob_history)
                    if feat is not None:
                        feat_arr = features_to_array(feat)
                        if feat_arr is not None and not np.any(np.isnan(feat_arr)):
                            prob = meta_model.predict_proba(feat_arr)[0, 1]
                            if prob < meta_threshold:
                                print(f"  [{ts}] META-FILTER {s}: prob={prob:.3f} < {meta_threshold} — SKIP")
                                continue
                            print(f"  [{ts}] META-PASS {s}: prob={prob:.3f} >= {meta_threshold} — ENTER")
                eff_lev = LEV_OVERRIDE.get(s, state['leverage'])
                pos_val = state['capital'] * state['stake_pct'] * eff_lev
                # Live margin guard: keep paper/live synced — don't open paper if live would fail margin
                # Use actual leverage after fallback (10x for capped symbols needs $4, 20x needs $2)
                if DEMO_LIVE:
                    try:
                        from demo_trader import get_balance as _gb
                        _bal = _gb('USDT')
                        # Estimate required margin at actual leverage (capped symbols need double)
                        _is_capped = s in ('BTRUSDT','TACUSDT','PUMPBTCUSDT','ARIAUSDT')
                        _eff_for_margin = 10 if _is_capped else eff_lev
                        _need = (state['capital'] * state['stake_pct'] * eff_lev) / _eff_for_margin
                        # For capped 10x: pos_val $40 at 10x needs $4; for 20x: $2
                        if _bal is not None and _bal < _need:
                            print(f"  [{ts}] MARGIN-SKIP {s}: need ${float(_need):.2f} have ${float(_bal):.2f} — SKIP (keeps paper/live synced)")
                            continue
                    except Exception:
                        pass
                qty = pos_val / prices[s]
                try:
                    from demo_trader import round_qty as _rq
                    qty = _rq(s, qty) if DEMO_LIVE else qty
                except Exception:
                    pass
                tp_p = prices[s] * (0.965 if d == 'short' else 1.035)
                sl_p = prices[s] * (1.02 if d == 'short' else 0.98)
                state['open_positions'][s] = {
                    'symbol': s, 'direction': d,
                    'entry_price': prices[s], 'quantity': qty,
                    'notional': pos_val, 'age': 0,
                    'tp_price': tp_p, 'sl_price': sl_p,
                    'entry_time': datetime.utcnow().isoformat(),
                }
                print(f"  [{ts}] OPENED {s}: {d.upper()} @ ${prices[s]:,.2f} | "
                       f"stake ${pos_val:,.2f} (margin ${state['capital']*state['stake_pct']:,.2f} x {eff_lev:g}x) "
                       f"| TP ${tp_p:,.2f} SL ${sl_p:,.2f} | TIMEOUT bar {H}")
                _notify(f"🎯 <b>OPENED {s} {d.upper()} — ALPHA 3 DRY</b>\n"
                        f"Entry: ${prices[s]:,.2f}\n"
                        f"TP: ${tp_p:,.2f} | SL: ${sl_p:,.2f} (market) | TIMEOUT bar {H}\n"
                        f"Notional: ${pos_val:,.2f} (margin ${state['capital']*state['stake_pct']:,.2f} × {eff_lev:g}x)\n"
                        f"Exit: TP 3.5% | SL 2% | TIMEOUT bar {H} (real-market)\n"
                        f"Equity: ${state['equity']:,.2f}")
                try: log_event("alpha3", "trade_open", {"symbol": s, "direction": d, "entry": round(prices[s],2), "notional": round(pos_val,2), "tp": round(tp_p,2), "sl": round(sl_p,2)})
                except Exception: pass
                if DEMO_LIVE:
                    try:
                        side = 'BUY' if d == 'long' else 'SELL'
                        # Use MARKET order for entry to match paper fill assumption.
                        # NOTE: no server-side bracket TP/SL — exits are enforced
                        # solely by this runner's barrier poll. Dual-exit (local +
                        # exchange algos) caused paper/demo divergence when an
                        # algo fired between polls while paper stayed open.
                        order, err = place_market_order(s, side, qty)
                        if order:
                            print(f"  📡 LIVE open {s}: {side} {qty:.6f} @ market -> {order.get('orderId')} {order.get('status')}")
                            _notify(f"📡 Live open {s}: {side} {qty:.6f} @ market")
                        elif err:
                            print(f"  ⚠️ LIVE open {s} failed: {err}")
                            _notify(f"⚠️ Live open {s} failed: {err}")
                        else:
                            print(f"  ⚠️ LIVE open {s}: no order and no error (unknown)")
                    except Exception as e:
                        print(f"  ⚠️ LIVE open {s} exception: {e}")
                        _notify(f"⚠️ Live open {s} exception: {e}")

    # Update effective equity (capital + unrealized) like Alpha 1
    eff = get_effective_equity(state, prices)
    state['effective_equity'] = eff
    state['peak_equity'] = max(state.get('peak_equity', eff), eff)
    _track_best_worst(state, eff)

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
                f"⚡ Cooldown: {state['cooldown_remaining']} bars")
        try: log_event("alpha3", "daily_summary", {"equity": round(state['equity'],2), "trades": state['total_trades'], "wr": round(wr,1)})
        except Exception: pass
    return state


def _signed_get(path, params=''):
    import hmac, hashlib
    from binance_config import ACTIVE_API_KEY, ACTIVE_API_SECRET
    ts = int(time.time() * 1000)
    q = f"timestamp={ts}&recvWindow=10000"
    if params:
        q += "&" + params
    sig = hmac.new(ACTIVE_API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    r = requests.get(f"{BINANCE_FAPI_BASE}{path}", params=f"{q}&signature={sig}",
                     headers={'X-MBX-APIKEY': ACTIVE_API_KEY}, timeout=10)
    return (r.json() if r.status_code == 200 else None)


def reconcile_on_startup(state):
    """Boot-time paper/demo reconciliation.

    The paper ledger is the strategy source of truth; the demo-fapi hedge must
    mirror it. After any crash/kill they can drift, so on every boot:
      1. Cancel ALL resting algo orders on managed assets (exits are enforced
         by this runner's poll only).
      2. Paper leg with NO demo position  -> close paper at market, booking
         realized PnL with reason RECONCILE.
      3. Demo position with NO paper leg -> reduce-only market close (orphan).
    Never raises: a failed reconcile logs and continues (boot must survive).
    """
    if not DEMO_LIVE:
        return
    ts = datetime.utcnow().strftime('%H:%M:%S')
    try:
        # 1) cancel resting algo orders for managed assets
        try:
            from demo_trader import cancel_algo_orders
            for s in ASSETS:
                try:
                    cancel_algo_orders(s)
                except Exception:
                    pass
        except Exception:
            pass

        pos = _signed_get('/fapi/v2/positionRisk')
        if pos is None:
            # NEVER treat an API failure as "demo flat" — that would close
            # every paper leg against a hedge that still exists.
            print(f"  [{ts}] RECONCILE skipped: positionRisk unavailable")
            return
        demo = {p['symbol']: p for p in pos if abs(float(p.get('positionAmt', 0))) > 0 and p['symbol'] in ASSETS}
        # Only reconcile our own universe — never touch the other Alpha's wallet (shared account)
        from demo_trader import place_market_order, round_qty as _rq

        # 2) paper open but demo flat -> book paper close at market
        for s in list(state.get('open_positions', {}).keys()):
            if s in demo:
                continue
            p = state['open_positions'][s]
            direction = p.get('direction', 'long')
            entry = float(p.get('entry_price', 0.0))
            qty = float(p.get('quantity', 0.0))
            px = get_price(s) or entry
            pct = ((px - entry) / entry if direction == 'long' else (entry - px) / entry) if entry else 0.0
            pnl_d = qty * (px - entry) * (1 if direction == 'long' else -1)
            pnl_d -= qty * (entry + px) * FEE_RATE
            state['capital'] += pnl_d
            state['equity'] = state['capital']
            state['total_trades'] += 1
            if pnl_d > 0:
                state['total_wins'] += 1
            else:
                state['total_losses'] += 1
            state['trades'].append({
                'symbol': s, 'direction': direction,
                'entry_price': entry, 'exit_price': px,
                'resolve': 'market', 'pnl_pct': pct,
                'pnl_dollars': pnl_d, 'reason': 'RECONCILE',
                'entry_time': p.get('entry_time'),
                'exit_time': datetime.utcnow().isoformat(),
            })
            log_trade(state['trades'][-1], state)
            del state['open_positions'][s]
            print(f"  [{ts}] RECONCILE {s}: demo flat -> closed paper leg "
                  f"({direction}, qty {qty}) @ {px} | PnL ${pnl_d:+,.2f}")
            _notify(f"🧹 <b>RECONCILE {s}</b>: demo flat → closed paper leg "
                    f"{direction.upper()} @ market | PnL ${pnl_d:+,.2f}")
            try: log_event("alpha3", "reconcile_paper_close", {"symbol": s, "pnl": round(pnl_d, 4), "price": px})
            except Exception: pass

        # 3) demo position with no paper leg -> orphan sweep
        for s, p in sorted(demo.items()):
            if s in state.get('open_positions', {}):
                continue
            amt = float(p['positionAmt'])
            side = 'SELL' if amt > 0 else 'BUY'
            qty = _rq(s, abs(amt))
            order, err = place_market_order(s, side, qty, reduce_only=True)
            if order:
                print(f"  [{ts}] RECONCILE {s}: orphan demo leg ({amt}) swept "
                      f"via {side} {qty} reduce-only")
                _notify(f"🧹 <b>RECONCILE {s}</b>: orphan demo position ({amt}) closed")
                try: log_event("alpha3", "reconcile_orphan_sweep", {"symbol": s, "amt": amt})
                except Exception: pass
            else:
                print(f"  [{ts}] RECONCILE {s}: orphan sweep FAILED ({err})")
                _notify(f"⚠️ <b>RECONCILE {s}</b>: orphan sweep failed: {err}")

        save_state(state)
    except Exception as e:
        print(f"  [{ts}] RECONCILE skipped: {e}")


def main():
    ap = argparse.ArgumentParser(description='Alpha 3 Dry Mode Runner')
    ap.add_argument('--once', action='store_true', help='Single cycle')
    ap.add_argument('--status', action='store_true', help='Show status')
    ap.add_argument('--interval', type=int, default=INTERVAL, help='Poll seconds')
    ap.add_argument('--seed', type=int, default=None,
                    help='RNG seed (default: OS entropy; fixed seed reproduces a run)')

    ap.add_argument('--stake', type=float, default=STAKE_PCT,
                    help='Margin fraction of equity per trade')
    ap.add_argument('--leverage', type=float, default=LEVERAGE,
                    help='Leverage multiplier on margin')
    ap.add_argument('--kill', action='store_true',
                    help='Set kill flag (running daemon flattens all positions + goes COOL) then exit')
    ap.add_argument('--disarm', action='store_true',
                    help='Clear kill switch and re-enable trading then exit')
    args = ap.parse_args()

    # Kill switch CLI (human-in-the-loop). The running daemon picks up the flag.
    if args.kill:
        KILL_FILE.touch()
        print("Kill flag set. The running Alpha 3 daemon will flatten all open positions "
              "and enter COOL (no new entries). Send /disarm to re-arm.")
        return
    if args.disarm:
        if KILL_FILE.exists():
            KILL_FILE.unlink()
        s = load_state(args.stake, args.leverage)
        disarm_kill_switch(s)
        save_state(s)
        print("Kill switch disarmed. Trading re-enabled.")
        return

    print(f"  RNG seed:  {args.seed if args.seed is not None else 'OS-entropy (non-repeating)'}")

    if args.status:
        s = load_state(args.stake, args.leverage)
        wr = 100*s['total_wins']/s['total_trades'] if s['total_trades'] else 0.0
        print(f"Alpha3 DRY (SIM) stake={args.stake*100:g}% x {args.leverage:g}x | equity ${s['equity']:,.2f} | "
              f"trades {s['total_trades']} ({s['total_wins']}W/{s['total_losses']}L, WR {wr:.1f}%) | "
              f"open {list(s['open_positions'].keys())} | cooldown {s['cooldown_remaining']} | trading {'ON' if s.get('trading_enabled', True) else 'PAUSED'}")
        return

    state = load_state(args.stake, args.leverage)
    # Source real equity from exchange when live (for correct position sizing)
    # DISABLED for paper run with fixed capital; to enable real balance sourcing, uncomment below
    # if USE_LIVE:
    #     try:
    #         from demo_trader import get_balance
    #         bal = get_balance()
    #         if bal is not None:
    #             state['capital'] = bal
    #             state['equity'] = bal
    #             print(f"  Live equity sourced from exchange: ${bal:,.2f}")
    #     except Exception as e:
    #         print(f"  WARNING: Could not fetch live balance for sizing: {e}")
    if state.get('kill_armed', False):
        print("  ⚠️  KILL SWITCH ARMED — runner is COOL (no new entries). Send /disarm to re-arm.")
    # Load meta-labeler
    meta_model, meta_threshold = load_meta_labeler()
    if meta_model:
        print(f"  Meta-labeler: LOADED (threshold={meta_threshold:.2f})")
    else:
        print(f"  Meta-labeler: NOT LOADED (running without filter)")
    # Set demo leverage (per-symbol overrides applied where the exchange rejects --leverage)
    print(f"  DEMO_LIVE={DEMO_LIVE} BASE={BINANCE_FAPI_BASE if DEMO_LIVE else 'N/A'} USE_LIVE={USE_LIVE}")
    if _DEMO_IMPORT_ERR:
        print(f"  DEMO import failed: {_DEMO_IMPORT_ERR[:800]}")
    if DEMO_LIVE:
        for _sym in ASSETS:
            _lev = LEV_OVERRIDE.get(_sym, args.leverage)
            res, err = set_leverage(_sym, _lev)
            if err:
                print(f"  Set leverage {_sym} {_lev:g}x -> FAILED {err}")
            else:
                print(f"  Set leverage {_sym} {_lev:g}x -> OK {res}")
    # Paper/demo reconciliation BEFORE trading (cancels stale algos, closes
    # paper legs whose demo hedge vanished, sweeps demo orphans).
    reconcile_on_startup(state)
    stake = state['capital'] * args.stake * args.leverage
    print("=" * 60)
    print("  ALPHA 3 DRY MODE RUNNER - TRIPLE-BARRIER (TP/SL/TIMEOUT)")
    print("=" * 60)
    print(f"  Assets:   {' + '.join([s.replace('USDT','') for s in ASSETS])} (60s polls, {len(ASSETS)} assets)")
    print(f"  Group:    {ALPHA3_GROUP}")
    print(f"  Engine:   momentum-K{K} direction, H={H} hold, CB {MAX_CONSEC}/{COOLDOWN}")
    print(f"  Exits:    TP 3.5% / SL 2% market | TIMEOUT at bar {H} (market price)")
    print(f"  Capital:  ${CAP:,.0f} USDT (synthetic)")
    print(f"  Staking:  {args.stake*100:g}% margin (${state['capital']*args.stake:,.2f}) x {args.leverage:g}x = ${stake:,.2f}/trade (compounding)")
    print(f"  Interval: {args.interval}s")
    from binance_config import BINANCE_API_BASE, USE_TESTNET
    print(f"  Binance:  {'TESTNET' if USE_TESTNET else 'MAINNET'} ({BINANCE_API_BASE})")
    print("=" * 60)
    sys.stdout.flush()

    running = True

    def handler(sig, frame):
        nonlocal running
        if FLATTEN_ON_SHUTDOWN:
            try:
                _flatten_positions(state)  # close positions, do NOT arm kill switch
                save_state(state)
            except Exception:
                pass
        print("\n  Shutting down...")
        running = False
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    cycle = 0
    while running:
        cycle += 1
        try:
            state = run_cycle(state, meta_model, meta_threshold)
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
