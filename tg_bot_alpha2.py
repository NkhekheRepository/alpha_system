#!/usr/bin/env python3
"""
Telegram Bot for Alpha 3% Synthetic Simulator Observability.
Dedicated bot: @LetapataBot (Nkhekhe Alpha Quant).
Reads alpha_3 simulation state. Commands: /status /pnl /live /stop /help
"""

import os, sys, json, logging, requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, BotCommand, MenuButtonDefault
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.insert(0, '/home/nkhekhe/alpha_system')
from notify import (
    generate_equity_chart, generate_trade_chart,
    notify_daily_summary
)

DATA_DIR = Path('/home/nkhekhe/alpha_system')
STATE_FILE = DATA_DIR / 'alpha3_state.json'

load_dotenv('/home/nkhekhe/alpha_system/.env')

TOKEN = os.environ.get('ALPHA2_TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('ALPHA2_TELEGRAM_CHAT_ID', '')
API = 'https://api.binance.com/api/v3'

# Alpha 3 simulation constants (mirror alpha_3.py)
P_WIN = 0.85
LOSS = -0.02
SYNTH_SIZING = [0.03, 1.0, 8.75, 35.0, 10.0]

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
            'last_update': None, 'start_time': None, 'simulation': 'alpha3'}

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
        "🤖 <b>Alpha 3% Synthetic Simulator</b>\n\n"
        "Simulation: continuous synthetic walk\n"
        "Sizing modes: f in {0.03, 1.0, 8.75, 35.0, 10.0}\n"
        "Formula: pnl_dollars = f × 100000.0 × pnl_pct\n"
        "SIM-ONLY: Deployment forbidden by protocol\n\n"
        "Commands:\n"
        "/status — Simulation status\n"
        "/pnl — Recent P&L summary\n"
        "/live — Live simulation stats\n"
        "/stop — Stop simulation (no-op, SIM-ONLY)\n"
        "/help — Command list",
        parse_mode='HTML'
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    # Alpha 3 simulation status
    params = (
        f"🤖 <b>Alpha 3% Synthetic Simulator</b>\n"
        f"📊 Win Probability: {P_WIN:.2f}\n"
        f"📉 Loss Amount: {LOSS:.2f}\n"
        f"💰 Sizing Modes: f={SYNTH_SIZING[0]:.2f}, f={SYNTH_SIZING[1]:.2f}, f={SYNTH_SIZING[2]:.2f}, f={SYNTH_SIZING[3]:.2f}, f={SYNTH_SIZING[4]:.2f}\n"
        f"💡 Formula: pnl_dollars = f × 100000.0 × pnl_pct\n"
        f"📡 Simulation: running continuously\n"
        f"🛡️ SIM-ONLY: Deployment forbidden by protocol"
    )
    await update.message.reply_text(params, parse_mode='HTML')

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
        direction = pos.get('direction', 'long')
        entry = pos['entry_price']
        tp = pos['tp_price']
        sl = pos['sl_price']
        qty = pos['quantity']
        current = prices.get(sym, entry)
        if direction == 'short':
            pnl_d = (entry - current) * qty
            pnl_pct = (entry - current) / entry * 100
        else:
            pnl_d = (current - entry) * qty
            pnl_pct = (current - entry) / entry * 100
        emoji = '🟢' if pnl_d >= 0 else '🔴'
        msg += (
            f"{emoji} <b>{base}/USDT</b> — {direction.upper()}\n"
            f"Entry: ${entry:,.2f} → Current: ${current:,.2f}\n"
            f"PnL: {pnl_pct:+.2f}% (${pnl_d:+,.2f})\n"
            f"Qty: {qty:.6f} {base}\n"
            f"TP: ${tp:,.2f} | SL: ${sl:,.2f}\n"
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
            f"{emoji} <b>{base}</b> — {t.get('direction','LONG').upper()} {t['reason']}\n"
            f"Entry: ${t['entry_price']:,.2f} → Exit: ${t['exit_price']:,.2f}\n"
            f"PnL: {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n\n"
        )
    msg += "━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    # Alpha 3 simulation P&L
    # synthetic: pnl_dollars = f * 100000.0 * pnl_pct with p=0.85
    # typical 50-trade walk at f=1.0: WR ~85-86%, PnL ~+$72k
    # at f=10.0: PnL ~+$720k (same WR, 10x PnL)
    # SIM-ONLY: Deployment forbidden
    await update.message.reply_text(
        "💰 <b>P&L SUMMARY — ALPHA 3% SIM-ONLY</b>\n\n"
        "Formula: pnl_dollars = f × 100000.0 × pnl_pct\n"
        "p = 0.85 win, p = 0.15 loss (±2%)\n"
        "SIZING MODES: f in {0.03, 1.0, 8.75, 35.0, 10.0}\n"
        "SIM-ONLY: Deployment forbidden by protocol\n\n"
        "Typical 50-trade walk (f=1.0):\n"
        "  WR ~85-86%, PnL ~+$72,000\n"
        "Typical 50-trade walk (f=10.0):\n"
        "  WR ~85-86%, PnL ~+$720,000\n"
        "SIM-ONLY: No real capital at risk",
        parse_mode='HTML'
    )
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_equity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chart = generate_equity_chart(
        equity_file=DATA_DIR / 'bidir_equity.csv',
        chart_path=DATA_DIR / 'bidir_equity_chart.png',
    )
    if chart:
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption="📊 Equity Curve — Alpha 2%")
    else:
        await update.message.reply_text("📊 Not enough data for chart (need 2+ data points)")

async def cmd_tradechart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chart = generate_trade_chart(
        state_file=DATA_DIR / 'bidir_state.json',
        chart_path=DATA_DIR / 'bidir_trade_chart.png',
    )
    if chart:
        with open(chart, 'rb') as f:
            await update.message.reply_photo(photo=f, caption="📈 Trade P&L Chart — Alpha 2%")
    else:
        await update.message.reply_text("📈 Not enough trades for chart (need 2+)")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    await update.message.reply_text(
        "🤖 <b>Alpha 2% Bot — Commands</b>\n\n"
        "/start — Welcome message\n"
        "/status — Full dashboard\n"
        "/positions — Open positions with live P&L\n"
        "/trades — Last 10 trades\n"
        "/pnl — P&L summary with unrealized\n"
        "/equity — Equity curve chart\n"
        "/tradechart — Trade P&L chart\n"
        "/help — This message\n"
        "/live — Start live dashboard (auto-updates every 30s)\n"
        "/stop — Stop live dashboard",
        parse_mode='HTML'
    )

live_messages = {}  # chat_id -> {"msg_id": int, "job": Job}

async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    chat_id = update.effective_chat.id
    state = load_state()
    prices = get_prices()
    unrealized_total, unrealized_details = calc_unrealized(state, prices)
    equity = state['equity']
    pnl = equity - 100000
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    effective = equity + unrealized_total
    dd = (state['peak_equity'] - effective) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    last = state.get('last_update', 'N/A')

    positions = state.get('open_positions', {})
    pos_lines = ""
    if unrealized_details:
        for d in unrealized_details:
            pos_lines += f"  {d}\n"
    elif positions:
        for sym, pos in positions.items():
            base = sym.replace('USDT', '')
            direction = pos.get('direction', 'long').upper()
            pos_lines += f"  {base}: {direction} @ ${pos['entry_price']:,.2f} | TP ${pos['tp_price']:,.2f} | SL ${pos['sl_price']:,.2f}\n"
    else:
        pos_lines = "  No open positions\n"

    msg = (
        f"📊 <b>ALPHA 2% LIVE DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🟢 LIVE — Auto-updating every 30s\n"
        f"Last updated: {datetime.utcnow().strftime('%H:%M:%S')}\n\n"
        f"💰 <b>Portfolio</b>\n"
        f"Equity: ${equity:,.2f}\n"
        f"Realized: ${pnl:+,.2f}\n"
        f"Unrealized: ${unrealized_total:+,.2f}\n"
        f"Total P&L: ${effective-100000:+,.2f} ({(effective-100000)/100000*100:+.2f}%)\n"
        f"Drawdown: {dd:.2f}%\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Open Positions</b>\n{pos_lines}"
        f"⚡ <b>Risk State</b>\n"
        f"Cooldown: {cooldown} bars\n"
        f"Circuit Breaker: {'ON (paused)' if cooldown > 0 else 'OFF'}\n"
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
            tt = s['total_trades']
            ww = s['total_wins']
            ll = s['total_losses']
            ww_per = ww / tt * 100 if tt > 0 else 0
            ee = e + u
            dd2 = (s['peak_equity'] - ee) / s['peak_equity'] * 100 if s['peak_equity'] > 0 else 0
            ct = s.get('cooldown_remaining', 0)
            pos2 = s.get('open_positions', {})
            pl2 = ""
            if d:
                for di in d:
                    pl2 += f"  {di}\n"
            elif pos2:
                for sym, pos in pos2.items():
                    bn = sym.replace('USDT', '')
                    dr = pos.get('direction', 'long').upper()
                    pl2 += f"  {bn}: {dr} @ ${pos['entry_price']:,.2f} | TP ${pos['tp_price']:,.2f} | SL ${pos['sl_price']:,.2f}\n"
            else:
                pl2 = "  No open positions\n"
            new_msg = (
                f"📊 <b>ALPHA 2% LIVE DASHBOARD</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"🟢 LIVE — Auto-updating every 30s\n"
                f"Last updated: {datetime.utcnow().strftime('%H:%M:%S')}\n\n"
                f"💰 <b>Portfolio</b>\n"
                f"Equity: ${e:,.2f}\n"
                f"Unrealized: ${u:+,.2f}\n"
                f"Total P&L: ${ee-100000:+,.2f} ({(ee-100000)/100000*100:+.2f}%)\n"
                f"Drawdown: {dd2:.2f}%\n\n"
                f"📈 <b>Performance</b>\n"
                f"Trades: {tt} ({ww}W / {ll}L)\n"
                f"Win Rate: {ww_per:.1f}%\n\n"
                f"🎯 <b>Open Positions</b>\n{pl2}"
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
        BotCommand("status", "Alpha 3 simulation status"),
        BotCommand("pnl", "P&L summary (SIM-ONLY)"),
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
    app.add_handler(CommandHandler("live", cmd_live))
    app.add_handler(CommandHandler("stop", cmd_stop))
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