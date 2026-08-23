#!/usr/bin/env python3
"""
Notification module for Telegram integration.
Sends formatted trade alerts from dry_runner.py.
"""

import os, json, csv, requests
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/home/nkhekhe/alpha_system/dry_data')
STATE_FILE = DATA_DIR / 'dry_state.json'

_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
_chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
_alpha2_token = os.environ.get('ALPHA2_TELEGRAM_BOT_TOKEN', '')
_alpha2_chat_id = os.environ.get('ALPHA2_TELEGRAM_CHAT_ID', '')

def _load_env():
    env_file = Path('/home/nkhekhe/alpha_system/.env')
    global _token, _chat_id, _alpha2_token, _alpha2_chat_id
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                _token = line.split('=', 1)[1]
            elif line.startswith('TELEGRAM_CHAT_ID='):
                _chat_id = line.split('=', 1)[1]
            elif line.startswith('ALPHA2_TELEGRAM_BOT_TOKEN='):
                _alpha2_token = line.split('=', 1)[1]
            elif line.startswith('ALPHA2_TELEGRAM_CHAT_ID='):
                _alpha2_chat_id = line.split('=', 1)[1]

def _resolve(bot='alpha1'):
    _load_env()
    if bot == 'alpha2':
        return _alpha2_token, _alpha2_chat_id
    return _token, _chat_id

def send_message(text, bot='alpha1'):
    token, chat_id = _resolve(bot)
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
        return r.status_code == 200
    except Exception:
        return False

def send_photo(photo_path, bot='alpha1'):
    token, chat_id = _resolve(bot)
    if not token or not chat_id:
        return False
    try:
        with open(photo_path, 'rb') as f:
            r = requests.post(
                f'https://api.telegram.org/bot{token}/sendPhoto',
                data={'chat_id': chat_id},
                files={'photo': f},
                timeout=15
            )
        return r.status_code == 200
    except Exception:
        return False

def notify_trade_open(trade, state, bot='alpha1'):
    s = trade['symbol']
    base = s.replace('USDT', '')
    entry = trade['entry_price']
    direction = trade.get('direction', 'long').upper()
    tp = trade.get('tp_price', entry * 1.02)
    sl = trade.get('sl_price', entry * 0.98)
    qty = trade['quantity']
    size = entry * qty
    pct = size / state['equity'] * 100 if state['equity'] > 0 else 0
    tp_pct = (tp / entry - 1) * 100 if entry else 0
    sl_pct = (sl / entry - 1) * 100 if entry else 0

    msg = (
        f"⚡ <b>NEW POSITION</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<b>{base}/USDT</b> — {direction}\n"
        f"Entry: ${entry:,.2f}\n"
        f"Qty: {qty:.6f} {base}\n"
        f"TP: ${tp:,.2f} ({tp_pct:+.1f}%)\n"
        f"SL: ${sl:,.2f} ({sl_pct:+.1f}%)\n"
        f"Size: ${size:,.0f} ({pct:.1f}% of equity)\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    send_message(msg, bot=bot)

def notify_trade_close(trade, state, bot='alpha1'):
    s = trade['symbol']
    base = s.replace('USDT', '')
    entry = trade['entry_price']
    exit_p = trade['exit_price']
    pnl_pct = trade['pnl_pct']
    pnl_d = trade['pnl_dollars']
    reason = trade['reason']
    direction = trade.get('direction', 'long').upper()
    equity = state['equity']
    wr = state['total_wins'] / state['total_trades'] * 100 if state['total_trades'] > 0 else 0
    total = state['total_trades']
    wins = state['total_wins']

    emoji = '🟢' if pnl_d > 0 else '🔴'
    label = 'TP HIT' if reason == 'TP' else 'SL HIT'

    msg = (
        f"{emoji} <b>TRADE CLOSED — {label}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<b>{base}/USDT</b> — {direction}\n"
        f"Entry: ${entry:,.2f} → Exit: ${exit_p:,.2f}\n"
        f"PnL: {pnl_pct:+.2%} (${pnl_d:+,.0f})\n"
        f"Equity: ${equity:,.2f}\n"
        f"Win Rate: {wr:.1f}% ({wins}/{total})\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    send_message(msg, bot=bot)

def notify_circuit_breaker(state, bot='alpha1'):
    cooldown = state.get('cooldown_remaining', 50)
    hours = cooldown * 5 / 60

    msg = (
        f"🛑 <b>CIRCUIT BREAKER ACTIVATED</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"3 consecutive losses reached\n"
        f"Cooldown: {cooldown} bars (~{hours:.1f} hours)\n"
        f"Trading paused automatically\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    send_message(msg, bot=bot)

def notify_daily_summary(state, bot='alpha1'):
    equity = state['equity']
    pnl = equity - 100000
    pnl_pct = pnl / 100000 * 100
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    dd = (state['peak_equity'] - equity) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)

    msg = (
        f"📊 <b>DAILY SUMMARY</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Portfolio</b>\n"
        f"Equity: ${equity:,.2f}\n"
        f"PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
        f"Drawdown: {dd:.2f}%\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"⚡ <b>Risk</b>\n"
        f"Circuit Breaker: {'ON' if cooldown > 0 else 'OFF'}\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    send_message(msg, bot=bot)

def format_status_dashboard(state):
    equity = state['equity']
    pnl = equity - 100000
    pnl_pct = pnl / 100000 * 100
    total = state['total_trades']
    wins = state['total_wins']
    losses = state['total_losses']
    wr = wins / total * 100 if total > 0 else 0
    dd = (state['peak_equity'] - equity) / state['peak_equity'] * 100 if state['peak_equity'] > 0 else 0
    cooldown = state.get('cooldown_remaining', 0)
    start = state.get('start_time', 'N/A')
    last = state.get('last_update', 'N/A')

    positions = state.get('open_positions', {})
    pos_lines = ""
    if positions:
        for sym, pos in positions.items():
            base = sym.replace('USDT', '')
            current = pos.get('entry_price', 0)
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
        f"PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
        f"Drawdown: {dd:.2f}%\n\n"
        f"📈 <b>Performance</b>\n"
        f"Trades: {total} ({wins}W / {losses}L)\n"
        f"Win Rate: {wr:.1f}%\n\n"
        f"🎯 <b>Open Positions</b>\n"
        f"{pos_lines}"
        f"📋 <b>Recent Trades</b>\n"
        f"{trade_lines}"
        f"⚡ <b>Risk State</b>\n"
        f"Cooldown: {cooldown} bars\n"
        f"Circuit Breaker: {'ON (paused)' if cooldown > 0 else 'OFF'}\n"
        f"━━━━━━━━━━━━━━━━━"
    )
    return msg

def generate_equity_chart(equity_file=None, chart_path=None):
    equity_file = equity_file or (DATA_DIR / 'dry_equity.csv')
    chart_path = chart_path or (DATA_DIR / 'equity_chart.png')
    if not equity_file.exists():
        return None

    times = []
    equities = []
    with open(equity_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                times.append(datetime.fromisoformat(row['time']))
                equities.append(float(row['equity']))
            except (ValueError, KeyError):
                continue

    if len(equities) < 2:
        return None

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')

    ax.plot(times, equities, color='#00d4ff', linewidth=2, label='Equity')
    base = equities[0]
    ax.axhline(y=base, color='#ffffff', linestyle='--', alpha=0.3, label='Starting Capital')

    ax.fill_between(times, equities, base, where=[e >= base for e in equities],
                     color='#00ff88', alpha=0.2)
    ax.fill_between(times, equities, base, where=[e < base for e in equities],
                     color='#ff4444', alpha=0.2)

    lo = min(equities + [base])
    hi = max(equities + [base])
    pad = max((hi - lo) * 0.15, hi * 0.02, 1e-9)
    ax.set_ylim(lo - pad, hi + pad)

    ax.set_title('Equity Curve', color='white', fontsize=14, fontweight='bold')
    ax.set_ylabel('Equity ($)', color='white', fontsize=12)
    ax.tick_params(colors='white')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    ax.legend(facecolor='#16213e', edgecolor='white', labelcolor='white')
    ax.grid(True, alpha=0.2, color='white')

    for spine in ax.spines.values():
        spine.set_color('white')
        spine.set_alpha(0.3)

    plt.tight_layout()
    chart_path = DATA_DIR / 'equity_chart.png' if chart_path is None else chart_path
    fig.savefig(chart_path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return chart_path

def generate_trade_chart(state_file=None, chart_path=None):
    state_file = state_file or (DATA_DIR / 'dry_state.json')
    chart_path = chart_path or (DATA_DIR / 'trade_chart.png')
    if not state_file.exists():
        return None

    with open(state_file, 'r') as f:
        state = json.load(f)

    trades = state.get('trades', [])
    if len(trades) < 2:
        return None

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    pnls = [t['pnl_dollars'] for t in trades]
    colors = ['#00ff88' if p > 0 else '#ff4444' for p in pnls]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig.patch.set_facecolor('#1a1a2e')

    ax1.bar(range(len(pnls)), pnls, color=colors, alpha=0.8)
    ax1.axhline(y=0, color='white', linestyle='-', alpha=0.5)
    ax1.set_title('Trade P&L', color='white', fontsize=14, fontweight='bold')
    ax1.set_ylabel('P&L ($)', color='white', fontsize=12)
    ax1.tick_params(colors='white')
    ax1.set_facecolor('#16213e')
    ax1.grid(True, alpha=0.2, color='white')

    cumulative = []
    running = 100000
    for p in pnls:
        running += p
        cumulative.append(running)

    ax2.plot(cumulative, color='#00d4ff', linewidth=2)
    ax2.axhline(y=100000, color='white', linestyle='--', alpha=0.3)
    ax2.fill_between(range(len(cumulative)), cumulative, 100000,
                     where=[c >= 100000 for c in cumulative], color='#00ff88', alpha=0.2)
    ax2.fill_between(range(len(cumulative)), cumulative, 100000,
                     where=[c < 100000 for c in cumulative], color='#ff4444', alpha=0.2)
    ax2.set_title('Cumulative P&L', color='white', fontsize=14, fontweight='bold')
    ax2.set_ylabel('Equity ($)', color='white', fontsize=12)
    ax2.tick_params(colors='white')
    ax2.set_facecolor('#16213e')
    ax2.grid(True, alpha=0.2, color='white')

    for ax in [ax1, ax2]:
        for spine in ax.spines.values():
            spine.set_color('white')
            spine.set_alpha(0.3)

    plt.tight_layout()
    chart_path = DATA_DIR / 'trade_chart.png'
    fig.savefig(chart_path, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return chart_path
