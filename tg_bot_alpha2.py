#!/usr/bin/env python3
"""
Telegram Bot for Alpha 3% Triple-Barrier Observability.
Dedicated bot: @LetapataBot (Nkhekhe Alpha Quant).
Reads alpha_3 simulation state. Commands: /status /pnl /live /stop /help
"""

import os, sys, json, logging, csv, requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, BotCommand, MenuButtonDefault
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import generate_equity_chart, generate_trade_chart
import analytics as vis
from scripts.meta_labeler_config import H, TP_PCT, SL_PCT, K, WIN_PCT, LOSS_PCT, LEVERAGE, STAKE_PCT
from binance_config import ALPHA3_ASSETS

DATA_DIR = Path(str(Path(__file__).resolve().parent))
STATE_FILE = DATA_DIR / 'dry_data' / 'alpha3_state.json'
CMD_FILE = DATA_DIR / 'dry_data' / 'alpha3_cmd.json'

load_dotenv(Path(__file__).resolve().parent / '.env')

TOKEN = os.environ.get('ALPHA2_TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('ALPHA2_TELEGRAM_CHAT_ID', '')
from binance_config import BINANCE_API_BASE
# Trading mode switch: testnet (default) or live
TRADING_MODE = os.getenv("TRADING_MODE", "testnet").lower()
if TRADING_MODE == "live":
    BINANCE_FAPI_BASE = "https://fapi.binance.com"
    print("LIVE TRADING ENABLED – REAL CAPITAL AT RISK")
else:
    BINANCE_FAPI_BASE = "https://testnet.binancefuture.com"
API = BINANCE_API_BASE


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def fmt_price(p):
    try:
        p = float(p)
    except Exception:
        return str(p)
    if p >= 10:
        return f"${p:,.2f}"
    elif p >= 1:
        return f"${p:,.4f}"
    elif p >= 0.01:
        return f"${p:,.5f}"
    else:
        return f"${p:,.6f}"

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {'equity': 100, 'capital': 100, 'peak_equity': 100,
            'start_capital': 100, 'stake_pct': 0.075, 'leverage': 50,
            'trades': [], 'open_positions': {}, 'total_trades': 0,
            'total_wins': 0, 'total_losses': 0, 'cooldown_remaining': 0,
            'last_update': None, 'start_time': None, 'simulation': 'alpha3'}

def check_chat(update: Update) -> bool:
    if not update or not update.effective_chat:
        return False
    return str(update.effective_chat.id) == CHAT_ID

try:
    from binance_config import ALPHA3_ASSETS, ALPHA3_GROUP
except Exception:
    ALPHA3_ASSETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT']
    ALPHA3_GROUP = 'unknown'

def get_prices():
    # bulk fetch -> 1 request vs 7 sequential (2s vs 14s) for <10s sync
    try:
        r = requests.get(f"{API}/ticker/price", timeout=5)
        data = r.json()
        # data is list of {symbol, price} when no symbol param
        if isinstance(data, list):
            wanted = set(ALPHA3_ASSETS)
            return {d['symbol']: float(d['price']) for d in data if d['symbol'] in wanted}
    except Exception:
        pass
    # fallback per-symbol
    prices = {}
    for sym in ALPHA3_ASSETS:
        try:
            r = requests.get(f"{API}/ticker/price", params={'symbol': sym}, timeout=5)
            prices[sym] = float(r.json()['price'])
        except Exception:
            pass
    return prices

def _kill_ledger_line():
    try:
        kl = DATA_DIR / 'dry_data' / 'alpha3_kill_log.csv'
        if not kl.exists():
            return "Kill log: none\n"
        rows = list(csv.reader(open(kl)))
        if len(rows) <= 1:
            return "Kill log: 0 engagements\n"
        n = len(rows) - 1
        tot = sum(float(r[3]) for r in rows[1:] if r and len(r) > 3)
        return f"Kill log: {n} engagement(s), total PnL ${tot:+,.2f}\n"
    except Exception:
        return ""


def calc_unrealized(state, prices):
    positions = state.get('open_positions', {})
    unrealized_total = 0.0
    details = []
    for sym, pos in positions.items():
        if sym not in prices:
            continue
        current = prices[sym]
        entry = pos['entry_price']
        qty = pos.get('quantity', 0.0)
        direction = pos.get('direction', 'long')
        if direction == 'short':
            pnl_d = (entry - current) * qty
            pnl_pct = (entry - current) / entry * 100
        else:
            pnl_d = (current - entry) * qty
            pnl_pct = (current - entry) / entry * 100
        unrealized_total += pnl_d
        base = sym.replace('USDT', '')
        emoji = '🟢' if pnl_d >= 0 else '🔴'
        details.append(f"{emoji} <b>{base}</b> {direction.upper()}: {fmt_price(current)} vs {fmt_price(entry)} → {pnl_pct:+.2f}% (${pnl_d:+,.2f})")
    return unrealized_total, details

def fetch_testnet_orders():
    """Fetch real open orders from Binance Testnet (if keys valid)."""
    try:
        from binance_config import BINANCE_API_BASE, ACTIVE_API_KEY, ACTIVE_API_SECRET, USE_TESTNET, sign_query
        if not USE_TESTNET or not ACTIVE_API_KEY or not ACTIVE_API_SECRET:
            return None, "Testnet keys not configured"
        # Use demo-fapi host directly for futures positions (BINANCE_API_BASE includes version)
        from binance_config import BINANCE_FAPI_BASE, USE_DEMO, BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET
        if USE_DEMO and BINANCE_DEMO_API_KEY:
            base = BINANCE_FAPI_BASE
            path = '/fapi/v2/positionRisk'
            key, sec = BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET
            is_futures = True
        else:
            base = BINANCE_API_BASE
            is_futures = 'fapi' in base
            path = '/fapi/v2/positionRisk' if is_futures else '/api/v3/openOrders'
            key, sec = ACTIVE_API_KEY, ACTIVE_API_SECRET
            if not key:
                return None, "Testnet keys not configured"
        signed = sign_query({'timestamp': 0}, secret=sec)
        h = {'X-MBX-APIKEY': key}
        r = requests.get(f'{base}{path}', params=signed, headers=h, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if is_futures:
                orders = [p for p in data if float(p.get('positionAmt', 0)) != 0]
            else:
                orders = data
            return orders, None
        else:
            print(f"[tg_bot] TESTNET GET FAIL {r.status_code}: {r.text[:200]}")
            return None, f"Testnet API {r.status_code}: {r.json().get('msg','')}"
    except Exception as e:
        return None, str(e)

async def error_handler(update, context):
    logger.error(f"Handler error: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Error processing command. Check logs."
            )
    except Exception:
        pass

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    lev = LEVERAGE
    stake_pct = STAKE_PCT * 100
    notional = 100 * STAKE_PCT * LEVERAGE
    await update.message.reply_text(
        "🎲 <b>Alpha 3% Dry Mode Runner</b>\n\n"
        "Triple-barrier paper trading (TP/SL/TIMEOUT)\n"
        "Engine: momentum-K30, H100 hold, CB 3/50\n"
        "Exits: TP 3.5% / SL 2% market | TIMEOUT bar 100 at market price\n"
        "Staking: 20% margin × 20x lev (compounds, $10 base)\n"
        "Commands:\n"
        "/status — Full dashboard\n"
        "/positions — Open positions with bar countdown\n"
        "/trades — Last 10 trades\n"
        "/pnl — P&L summary\n"
        "/equity — Equity curve chart\n"
        "/tradechart — Trade P&L chart\n"
        "/risk — Risk dashboard (Sharpe/Sortino/Calmar, DD, VaR)\n"
        "/attribution — P&L by symbol/exit/duration/hour\n"
        "/exposure — Current notional & leverage\n"
        "/health — Threshold alerts\n"
        "/live — Start live dashboard (auto-updates every 30s)\n"
        "/stop — Stop live dashboard\n"
        "/kill — 🛑 KILL SWITCH: close all open positions once, then COOL\n"
        "/disarm — Disarm kill switch, re-enable trading\n"
        "/help — Command list",
        parse_mode='HTML'
    )

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    CMD_FILE.write_text(json.dumps({'action': 'stop', 'ts': datetime.utcnow().isoformat()}))
    await update.message.reply_text(
        "\U0001F534 <b>Trading PAUSED</b>\nNo new entries will open. Open positions still resolve normally.",
        parse_mode='HTML')

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    CMD_FILE.write_text(json.dumps({'action': 'start', 'ts': datetime.utcnow().isoformat()}))
    await update.message.reply_text(
        "\U0001F7E2 <b>Trading ACTIVE</b>\nNew entries resume on next cycle.",
        parse_mode='HTML')


async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    CMD_FILE.write_text(json.dumps({'action': 'kill', 'ts': datetime.utcnow().isoformat()}))
    await update.message.reply_text(
        "\U0001F6D1 <b>KILL SWITCH ARMED</b>\nClosing ALL open positions now (once), then COOL. "
        "No new entries until /disarm.",
        parse_mode='HTML')


async def cmd_panic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_kill(update, context)


async def cmd_disarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    CMD_FILE.write_text(json.dumps({'action': 'disarm', 'ts': datetime.utcnow().isoformat()}))
    await update.message.reply_text(
        "\U0001F7E2 <b>KILL SWITCH DISARMED</b>\nTrading re-enabled.",
        parse_mode='HTML')

def build_status_text(state, live=False):
    base = state.get('start_capital', 100000.0)
    equity = state['equity']
    pnl = equity - base
    pnl_pct = pnl / base * 100
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    prices = get_prices()
    unrealized_total, unrealized_details = calc_unrealized(state, prices)
    effective = equity + unrealized_total
    dd = (state['peak_equity'] - effective) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    stake_pct = state.get('stake_pct', 0.075)
    lev = state.get('leverage', 50)
    last = state.get('last_update', 'N/A')
    total_pnl = pnl + unrealized_total
    total_pnl_pct = total_pnl / base * 100

    positions = state.get('open_positions', {})
    # fetch live testnet/demo positions for identical display
    live_orders, live_err = None, None
    live_by_sym = {}
    try:
        from binance_config import BINANCE_API_BASE, USE_TESTNET
        live_orders, live_err = fetch_testnet_orders()
        if live_orders is not None:
            for o in live_orders:
                if 'positionAmt' in o:
                    amt = float(o.get('positionAmt', 0))
                    if abs(amt) > 0:
                        live_by_sym[o['symbol']] = o
    except Exception:
        pass
    # check if paper and live are identical (same symbols + directions)
    identical = False
    if live_orders is not None and live_by_sym is not None:
        paper_syms = set(positions.keys())
        live_syms = set(live_by_sym.keys())
        if paper_syms == live_syms and len(paper_syms) == len(live_syms):
            # also check directions match
            match = True
            for sym in paper_syms:
                p_dir = positions[sym].get('direction', 'long')
                l_amt = float(live_by_sym[sym].get('positionAmt', 0))
                l_dir = 'long' if l_amt > 0 else 'short'
                if p_dir != l_dir:
                    match = False
                    break
            identical = match
    pos_lines = ""
    if identical:
        pos_lines = "  ✅ Telegram and Testnet identical — paper is source, live follows paper\n"
        # show paper positions (which now have live-capped qty/notional, so they are identical to live)
        for sym, pos in positions.items():
            base_s = sym.replace('USDT', '')
            entry = pos['entry_price']
            qty = pos['quantity']
            notional = pos['notional']
            direction = pos.get('direction', 'long')
            age = pos.get('age', 0)
            tp_disp = entry * (1 - WIN_PCT) if direction == 'short' else entry * (1 + WIN_PCT)
            sl_disp = entry * (1 - LOSS_PCT) if direction == 'short' else entry * (1 + LOSS_PCT)
            # prefer live upnl if available
            live = live_by_sym.get(sym, {})
            upnl = float(live.get('unRealizedProfit', 0)) if live else 0
            # fallback to paper calc if live upnl not available
            if live and upnl == 0:
                # compute paper upnl
                cur = prices.get(sym, entry)
                upnl = (cur - entry) * qty if direction == 'long' else (entry - cur) * qty
            emoji_up = '🟢' if upnl >= 0 else '🔴'
            pos_lines += (f"  {emoji_up} {base_s} {direction.upper()} {qty:.2f} @ {fmt_price(entry)} → {fmt_price(prices.get(sym, entry))} | uPnL ${upnl:+.2f}\n"
                          f"     bar {age}/{H} | stake ${notional:,.0f} | TP {fmt_price(tp_disp)} / SL {fmt_price(sl_disp)}\n")
    elif unrealized_details:
        for d in unrealized_details:
            pos_lines += f"  {d}\n"
        for sym, pos in positions.items():
            base_s = sym.replace('USDT', '')
            entry = pos['entry_price']
            direction = pos.get('direction', 'long')
            age = pos.get('age', 0)
            stake = pos.get('notional', 0)
            _tp = pos.get('tp_price', entry * (1.035 if pos.get('direction') == 'long' else 0.965))
            _sl = pos.get('sl_price', entry * (0.98 if pos.get('direction') == 'long' else 1.02))
            _tp_pct = abs(_tp - entry) / entry * 100 if entry else 0
            _sl_pct = abs(_sl - entry) / entry * 100 if entry else 0
            pos_lines += (f"     {base_s}: bar {age}/100 | stake ${stake:,.0f} | resolves → "
                          f"TP {_tp_pct:.2f}% ({fmt_price(_tp)}) / SL {_sl_pct:.2f}% ({fmt_price(_sl)})\n")
    elif positions:
        for sym, pos in positions.items():
            base_s = sym.replace('USDT', '')
            direction = pos.get('direction', 'long').upper()
            pos_lines += f"  {base_s}: {direction} @ {fmt_price(pos['entry_price'])}\n"
    else:
        pos_lines = "  No open positions\n"
        if live_by_sym:
            pos_lines += "  ⚠️ Live has positions but paper is flat — will reconcile at next runner cycle\n"
            for sym, live in live_by_sym.items():
                pos_lines += f"    {sym} {live.get('positionAmt')} @ {live.get('entryPrice')}\n"

    # Testnet sync status
    try:
        from binance_config import BINANCE_API_BASE, USE_TESTNET
        net_label = f"TESTNET ({BINANCE_API_BASE})" if USE_TESTNET else f"MAINNET ({BINANCE_API_BASE})"
        if live_orders is not None:
            is_pos = any('positionAmt' in o for o in live_orders) if live_orders else False
            label = "positions" if is_pos else "orders"
            if identical:
                testnet_line = f"✅ Synced to {net_label} | Testnet {label}: {len(live_orders)} open — Telegram is source, testnet follows"
            else:
                testnet_line = f"⚠️ Sync check: Paper {len(positions)} vs Testnet {len(live_by_sym)} — next cycle will make testnet follow paper"
                if live_err:
                    testnet_line += f" | {live_err}"
        elif live_err is not None and "not configured" in live_err:
            testnet_line = f"🔗 Price feed: {net_label} (paper positions above)"
        else:
            testnet_line = f"🔗 {net_label} | Testnet auth: {live_err} — paper positions above"
    except Exception:
        testnet_line = "🔗 Paper trading (dry mode)"
    header = "🟢 LIVE — auto-updating every 10s" if live else "DRY MODE"
    return (
        f"🎲 <b>ALPHA 3% — DRY MODE (TRIPLE-BARRIER)</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"{header}\n"
        f"Exits: TP 3.5% / SL 2% market barriers | TIMEOUT bar 100\n"
        f"{testnet_line}\n"
        f"Group: {ALPHA3_GROUP}\n"
        f"Staking: {stake_pct*100:g}% margin × {lev}x lev = ${base*stake_pct*lev:,.2f} notional/trade (compounds)\n\n"
        f"💰 <b>Portfolio (Paper)</b>\n"
        f"Equity: ${equity:,.2f} (base ${base:,.0f})\n"
        f"Realized: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
        f"Unrealized: ${unrealized_total:+,.2f}\n"
        f"<b>Total P&L: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)</b>\n"
        f"Drawdown: {dd:.2f}%\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Open Positions (Paper, synced to testnet price)</b>\n{pos_lines}"
        f"⚡ <b>Risk State</b>\n"
        f"Trading: {'\U0001F6D1 KILLED (cool)' if state.get('kill_armed', False) else ('\U0001F7E2 ACTIVE' if state.get('trading_enabled', True) else '\U0001F534 PAUSED')}\n"
        f"Best Return: {state.get('best_return_pct', 0.0)*100:+.2f}% | Worst Drawdown: {state.get('worst_drawdown_pct', 0.0)*100:.2f}%\n"
        # Kill-switch tracking ledger (local file, no network)
        f"{_kill_ledger_line()}"
        f"Cooldown: {cooldown} bars\n"
        f"Circuit Breaker: {'ON (paused)' if cooldown > 0 else 'OFF'}\n"
        f"Last Update: {last}"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    await update.message.reply_text(build_status_text(state), parse_mode='HTML')

async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    prices = get_prices()
    positions = state.get('open_positions', {})
    # Fetch real testnet orders for sync display
    t_orders, t_err = fetch_testnet_orders()
    from binance_config import BINANCE_API_BASE, USE_TESTNET
    net_tag = f"TESTNET ({BINANCE_API_BASE})" if USE_TESTNET else f"MAINNET ({BINANCE_API_BASE})"
    testnet_section = ""
    if t_orders is not None:
        if len(t_orders) == 0:
            testnet_section = f"\n🔗 <b>Testnet Exchange</b> ({net_tag}): No open positions\n"
        else:
            # Futures positionRisk has positionAmt/entryPrice, spot openOrders has side/type
            is_pos = any('positionAmt' in o for o in t_orders)
            if is_pos:
                testnet_section = f"\n🔗 <b>Testnet Exchange — Real Positions</b> ({net_tag}): {len(t_orders)} open\n"
                for o in t_orders[:5]:
                    testnet_section += f"  {o.get('symbol')} {o.get('positionAmt')} @ {o.get('entryPrice')} PnL {o.get('unRealizedProfit')}\n"
            else:
                testnet_section = f"\n🔗 <b>Testnet Exchange</b> ({net_tag}): {len(t_orders)} open order(s)\n"
                for o in t_orders[:5]:
                    testnet_section += f"  {o.get('symbol')} {o.get('side')} {o.get('type')} @ {o.get('price')} qty {o.get('origQty')}\n"
    else:
        if "not configured" in (t_err or ""):
            testnet_section = f"\n🔗 Price feed: {net_tag} | Paper positions above\n"
        else:
            testnet_section = f"\n🔗 {net_tag} | Testnet sync: {t_err} — showing paper positions\n"

    # check identical
    live_by_sym = {}
    if t_orders is not None:
        for o in t_orders:
            if 'positionAmt' in o and abs(float(o.get('positionAmt',0)))>0:
                live_by_sym[o['symbol']] = o
    identical = (set(positions.keys()) == set(live_by_sym.keys()) and len(positions)==len(live_by_sym) and all(positions[s].get('direction')==('long' if float(live_by_sym[s].get('positionAmt',0))>0 else 'short') for s in positions)) if positions and live_by_sym else False
    if not positions and not live_by_sym:
        await update.message.reply_text(f"🎯 No open positions — paper and testnet both flat{testnet_section}", parse_mode='HTML')
        return
    if not positions and live_by_sym:
        await update.message.reply_text(f"🎯 No paper open positions but live has {len(live_by_sym)} — will reconcile{testnet_section}", parse_mode='HTML')
        return
    if identical:
        # show live as source of truth
        stake_pct = state.get('stake_pct', 0.075)
        lev = state.get('leverage', 50)
        msg = f"✅ <b>OPEN POSITIONS — IDENTICAL</b> Paper = Testnet ({len(live_by_sym)} positions, {net_tag})\n━━━━━━━━━━━━━━━━━\n"
        for sym, live in live_by_sym.items():
            pos = positions[sym]
            base = sym.replace('USDT', '')
            direction = pos.get('direction', 'long')
            entry = float(live.get('entryPrice', pos['entry_price']))
            qty = abs(float(live.get('positionAmt', pos['quantity'])))
            notional = qty * entry
            current = prices.get(sym, entry)
            age = pos.get('age', 0)
            remaining = max(0, H - age)
            if direction == 'short':
                pnl_d = (entry - current) * qty
                pnl_pct = (entry - current) / entry * 100
            else:
                pnl_d = (current - entry) * qty
                pnl_pct = (current - entry) / entry * 100
            emoji = '🟢' if pnl_d >= 0 else '🔴'
            tp_d = entry * (1 - WIN_PCT) if direction == 'short' else entry * (1 + WIN_PCT)
            sl_d = entry * (1 - LOSS_PCT) if direction == 'short' else entry * (1 + LOSS_PCT)
            msg += (
                f"{emoji} <b>{base}/USDT</b> — {direction.upper()} {qty:.2f} @ {fmt_price(entry)} → {fmt_price(current)} | {pnl_pct:+.2f}% (${pnl_d:+.2f})\n"
                f"Notional ${notional:,.2f} | TP {fmt_price(tp_d)} / SL {fmt_price(sl_d)} | bar {age}/{H} (~{remaining*10//60} min)\n\n"
            )
        msg += testnet_section
        await update.message.reply_text(msg, parse_mode='HTML')
        return
    stake_pct = state.get('stake_pct', 0.075)
    lev = state.get('leverage', 50)
    msg = f"🎯 <b>OPEN POSITIONS — ALPHA 3 DRY</b> (synced to {net_tag}) ⚠️ Paper {len(positions)} vs Live {len(live_by_sym)} — not identical\n━━━━━━━━━━━━━━━━━\n"
    for sym, pos in positions.items():
        base = sym.replace('USDT', '')
        direction = pos.get('direction', 'long')
        entry = pos['entry_price']
        current = prices.get(sym, entry)
        age = pos.get('age', 0)
        remaining = max(0, H - age)
        notional = pos.get('notional', pos.get('quantity', 0) * entry)
        qty = pos.get('quantity', 0)
        # show live qty if available for this symbol
        live_qty = abs(float(live_by_sym[sym].get('positionAmt', qty))) if sym in live_by_sym else qty
        if live_qty != qty:
            notional = live_qty * entry
            qty = live_qty
        if direction == 'short':
            pnl_d = (entry - current) * qty
            pnl_pct = (entry - current) / entry * 100
        else:
            pnl_d = (current - entry) * qty
            pnl_pct = (current - entry) / entry * 100
        emoji = '🟢' if pnl_d >= 0 else '🔴'
        tp_d = entry * (1 - WIN_PCT) if direction == 'short' else entry * (1 + WIN_PCT)
        sl_d = entry * (1 - LOSS_PCT) if direction == 'short' else entry * (1 + LOSS_PCT)
        msg += (
            f"{emoji} <b>{base}/USDT</b> — {direction.upper()}\n"
            f"Entry: ${entry:,.2f} → Current: ${current:,.2f}\n"
            f"uPnL: {pnl_pct:+.2f}% (${pnl_d:+,.2f})\n"
            f"Notional: ${notional:,.2f} ({qty:.6f} {base}) = {stake_pct*100:g}% margin × {lev}x\n"
            f"TP ${tp_price:,.2f} / SL ${sl_price:,.2f} (market) | TIMEOUT bar 100\n"
            f"Hold: bar {age}/100 (~{remaining} min left)\n"
            f"Opened: {pos.get('entry_time', 'N/A')}\n\n"
        )
    # Show paper TP/SL levels (direction-aware)
    for sym2, pos2 in state.get('open_positions', {}).items():
        if 'tp_price' in pos2:
            entry_price = pos2["entry_price"]
            tp_price = pos2["tp_price"]
            sl_price = pos2["sl_price"]
            abs_tp_pct = abs(tp_price - entry_price) / entry_price * 100
            abs_sl_pct = abs(sl_price - entry_price) / entry_price * 100
            msg += f"     {base_s}: bar {age}/100 | resolves → TP {abs_tp_pct:.2f}% (${pos2["tp_price"]:,.2f}) / SL {abs_sl_pct:.2f}% (${pos2["sl_price"]:,.2f})\n"
    msg += testnet_section
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    trades = state.get('trades', [])[-10:]
    if not trades:
        await update.message.reply_text("📋 No trades yet", parse_mode='HTML')
        return
    msg = "📋 <b>LAST 10 TRADES — ALPHA 3 DRY</b>\n━━━━━━━━━━━━━━━━━\n"
    for t in reversed(trades):
        base = t['symbol'].replace('USDT', '')
        emoji = '🟢' if t['pnl_dollars'] > 0 else '🔴'
        msg += (
            f"{emoji} <b>{base}</b> — {t.get('direction','LONG').upper()} {t['reason']}\n"
            f"Entry: {fmt_price(t['entry_price'])} → Exit: {fmt_price(t['exit_price'])}\n"
            f"PnL: {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n\n"
        )
    msg += "━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    base = state.get('start_capital', 100000.0)
    equity = state['equity']
    pnl = equity - base
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    recent = state.get('trades', [])[-10:]
    trade_lines = ""
    for t in reversed(recent):
        base_s = t['symbol'].replace('USDT', '')
        emoji = '🟢' if t['pnl_dollars'] > 0 else '🔴'
        trade_lines += (f"  {emoji} {base_s} {t.get('direction','long').upper()} "
                        f"{t['reason']} | {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.2f})\n")
    if not trade_lines:
        trade_lines = "  No trades yet\n"
    msg = (
        f"💰 <b>P&L — ALPHA 3% DRY MODE</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Equity: ${equity:,.2f} (base ${base:,.0f})\n"
        f"<b>Total P&L: ${pnl:+,.2f} ({pnl/base*100:+.2f}%)</b>\n\n"
        f"📈 <b>Stats</b>\n"
        f"Total: {total} | Wins: {wins} | Losses: {losses}\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"📜 <b>Recent Trades</b>\n{trade_lines}"
    )
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_equity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chart = generate_equity_chart(
        equity_file=DATA_DIR / 'dry_data' / 'alpha3_equity.csv',
        chart_path=DATA_DIR / 'dry_data' / 'alpha3_equity_chart.png',
    )
    if chart:
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption="📊 Equity Curve — Alpha 3% Dry (SIM)")
    else:
        await update.message.reply_text("📊 Not enough data for chart (need 2+ data points)")

async def cmd_tradechart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chart = generate_trade_chart(
        state_file=STATE_FILE,
        chart_path=DATA_DIR / 'dry_data' / 'alpha3_trade_chart.png',
    )
    if chart:
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption="📈 Trade P&L Chart — Alpha 3% Dry (SIM)")
    else:
        await update.message.reply_text("📈 Not enough trades for chart (need 2+)")

async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        r = vis.get_risk_report(STATE_FILE)
        txt = vis.format_risk_telegram(r, "Alpha 3%")
        await update.message.reply_text(txt, parse_mode='HTML')
    except Exception as e:
        logger.error(f"risk error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Risk error: {e}")

async def cmd_attribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        a = vis.get_attribution_report(STATE_FILE)
        txt = vis.format_attribution_telegram(a, "Alpha 3%")
        await update.message.reply_text(txt, parse_mode='HTML')
    except Exception as e:
        logger.error(f"attribution error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Attribution error: {e}")

async def cmd_exposure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        txt = vis.format_exposure_telegram(STATE_FILE, "Alpha 3%")
        await update.message.reply_text(txt, parse_mode='HTML')
    except Exception as e:
        logger.error(f"exposure error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Exposure error: {e}")

async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        h = vis.health_checks(STATE_FILE)
        emoji = "🟢" if h['level']=="OK" else "🟡" if h['level']=="WARN" else "🔴"
        lines = [f"{emoji} <b>Alpha 3% HEALTH</b>", f"Level: <b>{h['level']}</b>", f"DD {h['dd']*100:.2f}% PF {h['pf']:.2f} Sharpe {h['sharpe']:.2f}"]
        if h['alerts']:
            lines.append("Alerts:")
            esc = lambda s: (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
            for a in h['alerts']:
                lines.append(f"  • {esc(a)}")
        else:
            lines.append("✅ All thresholds OK")
        lines.append(f"\n<i>Thresholds: DD 5%/10%, PF 1.0, Sharpe 0.5, Ulcer 3%, Corr 0.80, TO 85%</i>")
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')
    except Exception as e:
        logger.error(f"health error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Health error: {e}")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    await update.message.reply_text(
        "🎲 <b>Alpha 3% Dry Mode — Commands</b>\n\n"
        "/start — Welcome message\n"
        "/status — Full dashboard\n"
        "/positions — Open positions with bar countdown\n"
        "/trades — Last 10 trades\n"
        "/pnl — P&L summary\n"
        "/equity — Equity curve chart\n"
        "/tradechart — Trade P&L chart\n"
        "/risk — Risk dashboard (Sharpe/Sortino/Calmar, DD, VaR)\n"
        "/attribution — P&L by symbol/exit/duration/hour\n"
        "/exposure — Current notional & leverage\n"
        "/health — Threshold alerts\n"
        "/live — Start live dashboard (auto-updates every 30s)\n"
        "/stop — Stop live dashboard\n"
        "/pause — Pause new trade entries\n"
        "/resume — Resume trading\n"
        "/kill — 🛑 KILL SWITCH: close all open positions once, then COOL\n"
        "/panic — Alias for /kill\n"
        "/disarm — Disarm kill switch, re-enable trading\n"
        "/help — This message",
        parse_mode='HTML'
    )

live_messages = {}

async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chat_id = update.effective_chat.id
    state = load_state()
    sent = await update.message.reply_text(
        build_status_text(state, live=True), parse_mode='HTML')
    msg_id = sent.message_id

    async def auto_edit(context: ContextTypes.DEFAULT_TYPE):
        try:
            s = load_state()
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=build_status_text(s, live=True), parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Auto-edit error: {e}")

    job = context.job_queue.run_repeating(
        auto_edit, interval=10, first=10, chat_id=chat_id
    )
    live_messages[chat_id] = {"msg_id": msg_id, "job": job}

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chat_id = update.effective_chat.id
    if chat_id in live_messages:
        job = live_messages[chat_id]["job"]
        job.schedule_removal()
        del live_messages[chat_id]
        await update.message.reply_text("✅ Live dashboard stopped.", parse_mode='HTML')
    else:
        await update.message.reply_text("ℹ️ No live dashboard running.", parse_mode='HTML')

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Welcome message"),
        BotCommand("status", "Full dashboard (synced to testnet)"),
        BotCommand("positions", "Open positions + testnet sync"),
        BotCommand("trades", "Last 10 trades"),
        BotCommand("pnl", "P&L summary"),
        BotCommand("equity", "Equity curve chart"),
        BotCommand("tradechart", "Trade P&L chart"),
        BotCommand("risk", "Risk dashboard — Sharpe/DD/VaR"),
        BotCommand("attribution", "P&L attribution by symbol/reason"),
        BotCommand("exposure", "Current notional & leverage"),
        BotCommand("health", "Health alerts vs thresholds"),
        BotCommand("live", "Start live dashboard (auto-updates every 30s)"),
        BotCommand("stop", "Stop live dashboard"),
        BotCommand("pause", "Pause new trade entries"),
        BotCommand("resume", "Resume trading"),
        BotCommand("kill", "KILL SWITCH: close all positions once, then COOL"),
        BotCommand("panic", "Alias for /kill"),
        BotCommand("disarm", "Disarm kill switch, re-enable trading"),
        BotCommand("help", "Command list"),
    ])
    await app.bot.set_chat_menu_button(
        chat_id=CHAT_ID,
        menu_button=MenuButtonDefault(),
    )

def main():
    if not TOKEN:
        print("ERROR: ALPHA2_TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("equity", cmd_equity))
    app.add_handler(CommandHandler("tradechart", cmd_tradechart))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("attribution", cmd_attribution))
    app.add_handler(CommandHandler("exposure", cmd_exposure))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("live", cmd_live))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CommandHandler("panic", cmd_panic))
    app.add_handler(CommandHandler("disarm", cmd_disarm))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_error_handler(error_handler)

    print("="*60)
    print("  TELEGRAM BOT — ALPHA 3% SIM OBSERVER (Nkhekhe Alpha Quant)")
    print("="*60)
    print(f"  Token: {TOKEN[:10]}...{TOKEN[-5:]}")
    print(f"  Chat ID: {CHAT_ID}")
    print(f"  Status: ONLINE")
    print("="*60)
    sys.stdout.flush()

    app.run_polling(
        drop_pending_updates=True,
        poll_interval=2.0,
        timeout=10,
        bootstrap_retries=3,
    )

if __name__ == '__main__':
    main()