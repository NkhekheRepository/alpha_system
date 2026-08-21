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
from notify import generate_equity_chart, generate_trade_chart

DATA_DIR = Path('/home/nkhekhe/alpha_system')
STATE_FILE = DATA_DIR / 'dry_data' / 'alpha3_state.json'

load_dotenv('/home/nkhekhe/alpha_system/.env')

TOKEN = os.environ.get('ALPHA2_TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('ALPHA2_TELEGRAM_CHAT_ID', '')
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
            'last_update': None, 'start_time': None, 'simulation': 'alpha3'}

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
        "🎲 <b>Alpha 3% Dry Mode Runner</b>\n\n"
        "Synthetic-resolution paper trading (SIM ONLY)\n"
        "Engine: momentum-K10, H15 hold, CB 3/50\n"
        "Resolve: p=0.85 ±2% | PnL = f×100000×pct\n"
        "Mode: f=10.0 (±$20,000 per trade)\n"
        "🛑 NO CAPITAL — deployment forbidden\n\n"
        "Commands:\n"
        "/status — Full dashboard\n"
        "/positions — Open positions with bar countdown\n"
        "/trades — Last 10 trades\n"
        "/pnl — P&L summary\n"
        "/equity — Equity curve chart\n"
        "/tradechart — Trade P&L chart\n"
        "/live — Start live dashboard (auto-updates every 30s)\n"
        "/stop — Stop live dashboard\n"
        "/help — Command list",
        parse_mode='HTML'
    )

def build_status_text(state, live=False):
    equity = state['equity']
    pnl = equity - 100000
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    dd = (state['peak_equity'] - equity) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    f_mode = state.get('f_mode', '?')
    last = state.get('last_update', 'N/A')
    positions = state.get('open_positions', {})
    pos_lines = ""
    if positions:
        for sym, pos in positions.items():
            base = sym.replace('USDT', '')
            d = pos.get('direction', 'long').upper()
            age = pos.get('age', 0)
            pos_lines += f"  {base}: {d} @ ${pos['entry_price']:,.2f} | bar {age}/{15}\n"
    else:
        pos_lines = "  No open positions\n"
    header = "🟢 LIVE — auto-updating every 30s" if live else "🛑 SIMULATION ONLY — NO CAPITAL"
    return (
        f"🎲 <b>ALPHA 3% — DRY MODE (SYNTHETIC)</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"{header}\n"
        f"Resolve: p=0.85 ±2% | PnL = f×100000×pct\n\n"
        f"💰 <b>Portfolio</b>\n"
        f"Equity: ${equity:,.2f}\n"
        f"P&L: ${pnl:+,.2f} ({pnl/100000*100:+.2f}%)\n"
        f"Max DD: {dd:.2f}%\n"
        f"Sizing mode: f={f_mode}\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Open Positions</b>\n{pos_lines}"
        f"⚡ <b>Risk State</b>\n"
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
    positions = state.get('open_positions', {})
    if not positions:
        await update.message.reply_text("🎯 No open positions", parse_mode='HTML')
        return
    msg = "🎯 <b>OPEN POSITIONS — ALPHA 3 DRY</b>\n━━━━━━━━━━━━━━━━━\n"
    for sym, pos in positions.items():
        base = sym.replace('USDT', '')
        direction = pos.get('direction', 'long').upper()
        entry = pos['entry_price']
        age = pos.get('age', 0)
        remaining = max(0, 15 - age)
        msg += (
            f"🎲 <b>{base}/USDT</b> — {direction}\n"
            f"Entry: ${entry:,.2f}\n"
            f"Hold: bar {age}/15 (resolves in ~{remaining} min)\n"
            f"Outcome: p=0.85 → +2% / −2% | ±${state.get('f_mode', 10)*2000:,.0f}\n"
            f"Opened: {pos.get('entry_time', 'N/A')}\n\n"
        )
    msg += "━━━━━━━━━━━━━━━━━\n🛑 SIMULATION ONLY — NO CAPITAL"
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
            f"Entry: ${t['entry_price']:,.2f} → Exit: ${t['exit_price']:,.2f}\n"
            f"PnL: {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n\n"
        )
    msg += "━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_chat(update):
        return
    state = load_state()
    equity = state['equity']
    pnl = equity - 100000
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    recent = state.get('trades', [])[-10:]
    trade_lines = ""
    for t in reversed(recent):
        base = t['symbol'].replace('USDT', '')
        emoji = '🟢' if t['pnl_dollars'] > 0 else '🔴'
        trade_lines += (f"  {emoji} {base} {t.get('direction','long').upper()} "
                        f"{t['reason']} | {t['pnl_pct']:+.2%} (${t['pnl_dollars']:+,.0f})\n")
    if not trade_lines:
        trade_lines = "  No trades yet\n"
    msg = (
        f"💰 <b>P&L — ALPHA 3% DRY MODE</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🛑 SIMULATION ONLY — NO CAPITAL\n\n"
        f"Equity: ${equity:,.2f}\n"
        f"<b>Total P&L: ${pnl:+,.2f} ({pnl/100000*100:+.2f}%)</b>\n\n"
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
        "/live — Start live dashboard (auto-updates every 30s)\n"
        "/stop — Stop live dashboard\n"
        "/help — This message\n\n"
        "🛑 SIMULATION ONLY — NO CAPITAL",
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
        BotCommand("positions", "Open positions with bar countdown"),
        BotCommand("trades", "Last 10 trades"),
        BotCommand("pnl", "P&L summary"),
        BotCommand("equity", "Equity curve chart"),
        BotCommand("tradechart", "Trade P&L chart"),
        BotCommand("live", "Start live dashboard (auto-updates every 30s)"),
        BotCommand("stop", "Stop live dashboard"),
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