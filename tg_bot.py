#!/usr/bin/env python3
"""
Telegram Bot for Alpha 1% Dry Mode Observability.
Async bot with commands: /status, /positions, /trades, /pnl, /equity, /help
Sends trade notifications and daily summaries.
"""

import os, sys, json, logging, requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, BotCommand, MenuButtonDefault
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import (
    format_status_dashboard, generate_equity_chart, generate_trade_chart,
    send_message, notify_daily_summary
)
import analytics as vis

DATA_DIR = Path(__file__).resolve().parent / 'dry_data'
STATE_FILE = DATA_DIR / 'dry_state.json'
CMD_FILE = DATA_DIR / 'alpha1_cmd.json'

load_dotenv(Path(__file__).resolve().parent / '.env')

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
API = 'https://api.binance.com/api/v3'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {'equity': 100000, 'capital': 100000, 'peak_equity': 100000,
            'trades': [], 'open_positions': {}, 'total_trades': 0,
            'total_wins': 0, 'total_losses': 0, 'cooldown_remaining': 0,
            'last_update': None, 'start_time': None}

def get_prices():
    prices = {}
    for sym in ['BTCUSDT', 'ETHUSDT']:
        try:
            r = requests.get(f"{API}/ticker/price", params={'symbol': sym}, timeout=5)
            prices[sym] = float(r.json()['price'])
        except Exception:
            pass
    return prices

def calc_unrealized(state, prices):
    positions = state.get('open_positions', {})
    unrealized_total = 0.0
    details = []
    for sym, pos in positions.items():
        if sym not in prices:
            continue
        current = prices[sym]
        entry = pos['entry_price']
        qty = pos['quantity']
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
        details.append(f"{emoji} <b>{base}</b> {direction.upper()}: ${current:,.2f} vs ${entry:,.2f} → {pnl_pct:+.2f}% (${pnl_d:+,.2f})")
    return unrealized_total, details

live_messages = {}  # chat_id -> {"msg_id": int, "job": Job}

def check_chat(update: Update) -> bool:
    if not update or not update.effective_chat:
        return False
    return str(update.effective_chat.id) == CHAT_ID

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
    await update.message.reply_text(
        "🤖 <b>Alpha 1% Bot Online</b>\n\n"
        "Monitoring: BTC + ETH (5m)\n"
        "Mode: Paper Trading (Dry)\n\n"
        "Commands:\n"
        "/status — Full dashboard\n"
        "/positions — Open positions\n"
        "/trades — Last 10 trades\n"
        "/pnl — P&L summary\n"
        "/equity — Equity chart\n"
        "/tradechart — Trade chart\n"
        "/risk — Risk dashboard (Sharpe/Sortino/Calmar, DD, VaR)\n"
        "/attribution — P&L by symbol/exit/duration/hour\n"
        "/exposure — Current notional & leverage\n"
        "/health — Threshold alerts\n"
        "/stop — Pause new trade entries\n"
        "/resume — Resume trading\n"
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

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    prices = get_prices()
    unrealized_total, unrealized_details = calc_unrealized(state, prices)
    equity = state['equity']
    pnl = equity - 100000
    pnl_pct = pnl / 100000 * 100
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    effective = equity + unrealized_total
    dd = (state['peak_equity'] - effective) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    start = state.get('start_time', 'N/A')
    last = state.get('last_update', 'N/A')

    total_pnl = pnl + unrealized_total
    total_pnl_pct = total_pnl / 100000 * 100

    positions = state.get('open_positions', {})
    pos_lines = ""
    if unrealized_details:
        for d in unrealized_details:
            pos_lines += f"  {d}\n"
    elif positions:
        for sym, pos in positions.items():
            base = sym.replace('USDT', '')
            pos_lines += f"  {base}: LONG @ ${pos['entry_price']:,.2f} | TP ${pos['tp_price']:,.2f} | SL ${pos['sl_price']:,.2f}\n"
    else:
        pos_lines = "  No open positions\n"

    recent = state.get('trades', [])[-5:]
    trade_lines = ""
    if recent:
        for t in reversed(recent):
            base = t['symbol'].replace('USDT', '')
            emoji = '🟢' if t['pnl_dollars'] > 0 else '🔴'
            trade_lines += f"  {emoji} {base}: {t['reason']} @ ${t['exit_price']:,.2f} | {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n"
    else:
        trade_lines = "  No trades yet\n"

    msg = (
        f"📊 <b>DRY MODE DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Started: {start}\n"
        f"Last Update: {last}\n\n"
        f"💰 <b>Portfolio</b>\n"
        f"Equity: ${equity:,.2f}\n"
        f"Realized: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
        f"Unrealized: ${unrealized_total:+,.2f}\n"
        f"Total P&L: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)\n"
        f"Drawdown: {dd:.2f}%\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Open Positions</b>\n{pos_lines}"
        f"📋 <b>Recent Trades</b>\n{trade_lines}"
        f"⚡ <b>Risk State</b>\n"
        f"Cooldown: {cooldown} bars\n"
        f"Trading: {'\U0001F7E2 ACTIVE' if state.get('trading_enabled', True) else '\U0001F534 PAUSED'}\n"
        f"Circuit Breaker: {'ON (paused)' if cooldown > 0 else 'OFF'}\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    prices = get_prices()
    positions = state.get('open_positions', {})
    if not positions:
        await update.message.reply_text("🎯 No open positions", parse_mode='HTML')
        return
    msg = "🎯 <b>OPEN POSITIONS</b>\n━━━━━━━━━━━━━━━━━\n"
    for sym, pos in positions.items():
        base = sym.replace('USDT', '')
        entry = pos['entry_price']
        tp = pos['tp_price']
        sl = pos['sl_price']
        qty = pos['quantity']
        current = prices.get(sym, entry)
        pnl_d = (current - entry) * qty
        pnl_pct = (current - entry) / entry * 100
        emoji = '🟢' if pnl_d >= 0 else '🔴'
        msg += (
            f"{emoji} <b>{base}/USDT</b> — LONG\n"
            f"Entry: ${entry:,.2f} → Current: ${current:,.2f}\n"
            f"PnL: {pnl_pct:+.2f}% (${pnl_d:+,.2f})\n"
            f"Qty: {qty:.6f} {base}\n"
            f"TP: ${tp:,.2f} (+2%) | SL: ${sl:,.2f} (-2%)\n"
            f"Opened: {pos.get('entry_time', 'N/A')}\n\n"
        )
    msg += "━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    trades = state.get('trades', [])[-10:]
    if not trades:
        await update.message.reply_text("📋 No trades yet", parse_mode='HTML')
        return
    msg = "📋 <b>LAST 10 TRADES</b>\n━━━━━━━━━━━━━━━━━\n"
    for t in reversed(trades):
        base = t['symbol'].replace('USDT', '')
        emoji = '🟢' if t['pnl_dollars'] > 0 else '🔴'
        msg += (
            f"{emoji} <b>{base}</b> — {t['reason']}\n"
            f"Entry: ${t['entry_price']:,.2f} → Exit: ${t['exit_price']:,.2f}\n"
            f"PnL: {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n\n"
        )
    msg += "━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    prices = get_prices()
    equity = state['equity']
    realized = equity - 100000
    realized_pct = realized / 100000 * 100
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    unrealized_total, unrealized_details = calc_unrealized(state, prices)
    effective = equity + unrealized_total
    dd = (state['peak_equity'] - effective) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    last = state.get('last_update', 'N/A')

    total_pnl = realized + unrealized_total
    total_pnl_pct = total_pnl / 100000 * 100

    unrealized_section = ""
    if unrealized_details:
        for d in unrealized_details:
            unrealized_section += f"  {d}\n"
    else:
        unrealized_section = "  No open positions\n"

    msg = (
        f"💰 <b>P&L SUMMARY</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Equity: ${equity:,.2f}\n"
        f"Realized: ${realized:+,.2f} ({realized_pct:+.2f}%)\n"
        f"Unrealized: ${unrealized_total:+,.2f}\n"
        f"<b>Total P&L: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)</b>\n"
        f"Max Drawdown: {dd:.2f}%\n"
        f"Last Update: {last}\n\n"
        f"📈 <b>Stats</b>\n"
        f"Total: {total}\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Unrealized Positions</b>\n{unrealized_section}"
        f"⚡ <b>Risk</b>\n"
        f"Circuit Breaker: {'ON' if cooldown > 0 else 'OFF'}\n"
        f"Cooldown: {cooldown} bars\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_equity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chart = generate_equity_chart()
    if chart:
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption="📊 Equity Curve")
    else:
        await update.message.reply_text("📊 Not enough data for chart (need 2+ data points)")

async def cmd_tradechart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chart = generate_trade_chart()
    if chart:
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption="📈 Trade P&L Chart")
    else:
        await update.message.reply_text("📈 Not enough trades for chart (need 2+)")

async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        r = vis.get_risk_report(STATE_FILE)
        txt = vis.format_risk_telegram(r, "Alpha 1%")
        await update.message.reply_text(txt, parse_mode='HTML')
    except Exception as e:
        logger.error(f"risk error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Risk error: {e}")

async def cmd_attribution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        a = vis.get_attribution_report(STATE_FILE)
        txt = vis.format_attribution_telegram(a, "Alpha 1%")
        await update.message.reply_text(txt, parse_mode='HTML')
    except Exception as e:
        logger.error(f"attribution error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Attribution error: {e}")

async def cmd_exposure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    try:
        txt = vis.format_exposure_telegram(STATE_FILE, "Alpha 1%")
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
        lines = [f"{emoji} <b>Alpha 1% HEALTH</b>", f"Level: <b>{h['level']}</b>", f"DD {h['dd']*100:.2f}% PF {h['pf']:.2f} Sharpe {h['sharpe']:.2f}"]
        if h['alerts']:
            lines.append("Alerts:")
            for a in h['alerts']:
                lines.append(f"  • {a}")
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
        "🤖 <b>Alpha 1% Bot — Commands</b>\n\n"
        "/start — Welcome message\n"
        "/status — Full dashboard\n"
        "/positions — Open positions with live P&L\n"
        "/trades — Last 10 trades\n"
        "/pnl — P&L summary with unrealized\n"
        "/equity — Equity curve chart\n"
        "/tradechart — Trade P&L chart\n"
        "/risk — Risk dashboard (Sharpe/Sortino/Calmar, DD, VaR)\n"
        "/attribution — P&L by symbol/exit/duration/hour\n"
        "/exposure — Current notional & leverage\n"
        "/health — Threshold alerts\n"
        "/help — This message\n"
        "/live — Start live dashboard (auto-updates every 30s)\n"
        "/stop — Stop live dashboard",
        parse_mode='HTML'
    )

async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chat_id = update.effective_chat.id
    state = load_state()
    prices = get_prices()
    unrealized_total, unrealized_details = calc_unrealized(state, prices)
    equity = state['equity']
    pnl = equity - 100000
    pnl_pct = pnl / 100000 * 100
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    effective = equity + unrealized_total
    dd = (state['peak_equity'] - effective) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    start = state.get('start_time', 'N/A')
    last = state.get('last_update', 'N/A')
    total_pnl = pnl + unrealized_total
    total_pnl_pct = total_pnl / 100000 * 100

    positions = state.get('open_positions', {})
    pos_lines = ""
    if unrealized_details:
        for d in unrealized_details:
            pos_lines += f"  {d}\n"
    elif positions:
        for sym, pos in positions.items():
            base = sym.replace('USDT', '')
            pos_lines += f"  {base}: LONG @ ${pos['entry_price']:,.2f} | TP ${pos['tp_price']:,.2f} | SL ${pos['sl_price']:,.2f}\n"
    else:
        pos_lines = "  No open positions\n"

    recent = state.get('trades', [])[-5:]
    trade_lines = ""
    if recent:
        for t in reversed(recent):
            base = t['symbol'].replace('USDT', '')
            emoji = '🟢' if t['pnl_dollars'] > 0 else '🔴'
            trade_lines += f"  {emoji} {base}: {t['reason']} @ ${t['exit_price']:,.2f} | {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n"
    else:
        trade_lines = "  No trades yet\n"

    msg = (
        f"📊 <b>DRY MODE LIVE DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🟢 LIVE — Auto-updating every 30s\n"
        f"Started: {datetime.utcnow().strftime('%H:%M:%S')}\n\n"
        f"💰 <b>Portfolio</b>\n"
        f"Equity: ${equity:,.2f}\n"
        f"Realized: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
        f"Unrealized: ${unrealized_total:+,.2f}\n"
        f"Total P&L: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)\n"
        f"Drawdown: {dd:.2f}%\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Open Positions</b>\n{pos_lines}"
        f"📋 <b>Recent Trades</b>\n{trade_lines}"
        f"⚡ <b>Risk State</b>\n"
        f"Cooldown: {cooldown} bars\n"
        f"Circuit Breaker: {'ON (paused)' if cooldown > 0 else 'OFF'}\n"
        f"Last updated: {last}\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    sent = await update.message.reply_text(msg, parse_mode='HTML')
    msg_id = sent.message_id

    async def auto_edit(context: ContextTypes.DEFAULT_TYPE):
        try:
            s = load_state()
            p = get_prices()
            u, d = calc_unrealized(s, p)
            e = s['equity']
            pn = e - 100000
            pp = pn / 100000 * 100
            tt = s['total_trades']
            ww = s['total_wins']
            ll = s['total_losses']
            ww_per = ww / tt * 100 if tt > 0 else 0
            ee = e + u
            dd2 = (s['peak_equity'] - ee) / s['peak_equity'] * 100 if s['peak_equity'] > 0 else 0
            ct = s.get('cooldown_remaining', 0)
            st = s.get('start_time', 'N/A')
            lt = s.get('last_update', 'N/A')
            tp = pn + u
            tp_pct = tp / 100000 * 100
            pos2 = s.get('open_positions', {})
            pl2 = ""
            if d:
                for di in d:
                    pl2 += f"  {di}\n"
            elif pos2:
                for sym, pos in pos2.items():
                    bn = sym.replace('USDT', '')
                    pl2 += f"  {bn}: LONG @ ${pos['entry_price']:,.2f} | TP ${pos['tp_price']:,.2f} | SL ${pos['sl_price']:,.2f}\n"
            else:
                pl2 = "  No open positions\n"
            rl = s.get('trades', [])[-5:]
            tl = ""
            if rl:
                for t in reversed(rl):
                    bt = t['symbol'].replace('USDT', '')
                    emj = '🟢' if t['pnl_dollars'] > 0 else '🔴'
                    tl += f"  {emj} {bt}: {t['reason']} @ ${t['exit_price']:,.2f} | {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n"
            else:
                tl = "  No trades yet\n"
            new_msg = (
                f"📊 <b>DRY MODE LIVE DASHBOARD</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🟢 LIVE — Auto-updating every 30s\n"
                f"Last updated: {datetime.utcnow().strftime('%H:%M:%S')}\n\n"
                f"💰 <b>Portfolio</b>\n"
                f"Equity: ${e:,.2f}\n"
                f"Realized: ${pp:+,.2f} ({pp:+.2f}%)\n"
                f"Unrealized: ${u:+,.2f}\n"
                f"Total P&L: ${tp:+,.2f} ({tp_pct:+.2f}%)\n"
                f"Drawdown: {dd2:.2f}%\n\n"
                f"📈 <b>Performance</b>\n"
                f"Trades: {tt} ({ww}W / {ll}L)\n"
                f"Win Rate: {ww_per:.1f}%\n\n"
                f"🎯 <b>Open Positions</b>\n{pl2}"
                f"📋 <b>Recent Trades</b>\n{tl}"
                f"⚡ <b>Risk State</b>\n"
                f"Cooldown: {ct} bars\n"
                f"Circuit Breaker: {'ON (paused)' if ct > 0 else 'OFF'}\n"
                f"━━━━━━━━━━━━━━━━━"
            )
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=new_msg, parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Auto-edit error: {e}")

    job = context.job_queue.run_repeating(
        auto_edit, interval=30, first=35, chat_id=chat_id
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
        BotCommand("status", "Full dashboard"),
        BotCommand("positions", "Open positions with live P&L"),
        BotCommand("trades", "Last 10 trades"),
        BotCommand("pnl", "P&L summary with unrealized"),
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
        BotCommand("help", "Command list"),
    ])
    await app.bot.set_chat_menu_button(
        chat_id=CHAT_ID,
        menu_button=MenuButtonDefault(),
    )

def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
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
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_error_handler(error_handler)

    print("="*60)
    print("  TELEGRAM BOT — ALPHA 1% DRY MODE")
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
