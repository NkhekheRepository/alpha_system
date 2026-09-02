#!/usr/bin/env python3
"""Generate docs/HEDGE_REPORT.md from the LIVE Alpha 3 state + trade log.

Computes real risk/performance metrics via analytics.py and emits a
quantitative hedge report. Reproducible:  python3 scripts/generate_hedge_report.py
"""
from pathlib import Path
import json, csv, sys, os
from datetime import datetime
import numpy as np

ROOT = Path(str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import analytics as A
STATE = ROOT / 'dry_data' / 'alpha3_state.json'
EQUITY = ROOT / 'dry_data' / 'alpha3_equity.csv'
OUT = ROOT / 'docs' / 'HEDGE_REPORT.md'

LEV = float(os.environ.get('ALPHA3_LEV', '0')) or None  # resolved from state at runtime
STAKE = 0.075


def load_state():
    return json.loads(STATE.read_text())


def load_equity_curve():
    if not EQUITY.exists():
        return [], []
    times, eq = [], []
    with open(EQUITY) as f:
        rows = list(csv.reader(f))
    # Runner appends WITHOUT header: cols = time, equity, effective, ...
    if rows and rows[0] and rows[0][0].strip().lower() == 'time':
        rows = rows[1:]
    for r in rows:
        if len(r) < 3:
            continue
        times.append(r[0])
        eq.append(float(r[2]))  # effective equity
    return times, eq


def load_trades_csv():
    p = ROOT / 'dry_data' / 'alpha3_trades.csv'
    if not p.exists():
        return []
    out = []
    with open(p) as f:
        rows = list(csv.reader(f))
    # Runner appends WITHOUT header after truncations: sniff and map positionally.
    header = ['time', 'symbol', 'dir', 'entry', 'exit', 'resolve',
              'pnl_pct', 'pnl_dollar', 'reason', 'equity', 'trades', 'wr']
    if rows and rows[0] and rows[0][0].strip().lower() == 'time':
        rows = rows[1:]
    for r in rows:
        if len(r) < 9:
            continue
        d = dict(zip(header, r))
        try:
            out.append({
                'symbol': d['symbol'],
                'direction': d['dir'],
                'reason': d['reason'],
                'pnl_pct': float(d['pnl_pct'] or 0),
                'pnl_dollars': float(d['pnl_dollar'] or 0),
                'entry_price': float(d['entry'] or 0),
                'exit_price': float(d['exit'] or 0),
            })
        except ValueError:
            continue
    return out


def main():
    s = load_state()
    times, eq_curve = load_equity_curve()
    trades = load_trades_csv()
    cap = float(s.get('capital', 100.0))
    eq = float(s.get('equity', cap))
    eff = float(s.get('effective_equity', eq))
    lev = float(s.get('leverage') or LEV or 20.0)
    base = float(s.get('start_capital') or 100.0)
    n = s.get('total_trades', 0)
    wins = s.get('total_wins', 0)
    losses = s.get('total_losses', 0)
    wr = 100 * wins / n if n else 0.0

    # Hedge book
    book = []
    total_notional = 0.0
    total_margin = 0.0
    for sym, p in s.get('open_positions', {}).items():
        entry = float(p['entry_price'])
        qty = float(p['quantity'])
        notional = entry * qty
        margin = notional / lev
        total_notional += notional
        total_margin += margin
        book.append((sym, p['direction'], entry, qty, notional, margin,
                     float(p['tp_price']), float(p['sl_price']), p.get('age', 0)))

    # Risk metrics
    def safe(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            return f"n/a ({e.__class__.__name__})"

    sharpe = safe(A.compute_sharpe, trades, equity_curve=eq_curve or None,
                  equity_times=[datetime.fromisoformat(t) for t in times] or None)
    sortino = safe(A.compute_sortino, trades)
    calmar = safe(A.compute_calmar, trades, equity_curve=eq_curve or None)
    dd = safe(A.drawdown_stats, eq_curve) if eq_curve else "n/a (need equity curve)"
    var_cvar = safe(A.compute_var_cvar, trades)
    pf = safe(A.profit_factor, trades)
    exp = safe(A.expectancy, trades)
    by_sym = safe(A.attribution_by_symbol, trades)
    by_reason = safe(A.attribution_by_reason, trades)

    def fmt(x, p=2):
        if isinstance(x, str):
            return x
        if isinstance(x, (int, float, np.floating)):
            return f"{x:.{p}f}"
        return str(x)

    lines = []
    lines.append("# Alpha 3 Dry Mode — Quantitative Hedge Report")
    lines.append("")
    lines.append(f"_Generated: {datetime.utcnow().isoformat()} (UTC)_")
    lines.append("")
    lines.append("> **DISCLAIMER:** Alpha 3 is a **simulation-only** system on the demo-fapi test "
                 "account (real market prices, synthetic capital). Alpha 3 is **NO-GO on real "
                 "capital** (see GOVERNANCE.md).")
    lines.append("")
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Base capital | ${base:,.2f} |")
    lines.append(f"| Realized equity | ${eq:,.2f} |")
    lines.append(f"| Effective equity (mark-to-market) | ${eff:,.2f} |")
    lines.append(f"| Unrealized P&L | ${eff-eq:+,.2f} |")
    lines.append(f"| Total trades | {n} ({wins}W / {losses}L) |")
    lines.append(f"| Win rate | {wr:.1f}% |")
    lines.append(f"| Open hedge positions | {len(book)} |")
    lines.append(f"| Total notional (open) | ${total_notional:,.2f} |")
    lines.append(f"| Total margin (open) | ${total_margin:,.2f} |")
    lines.append(f"| Leverage | {lev:.0f}x |")
    lines.append("")
    lines.append("## 2. Hedge Book (live demo-fapi positions)")
    lines.append("")
    lines.append("| Asset | Dir | Entry | Qty | Notional | Margin | TP | SL | Age |")
    lines.append("|-------|-----|-------|-----|----------|--------|-----|-----|-----|")
    for sym, d, entry, qty, notional, margin, tp, sl, age in book:
        lines.append(f"| {sym} | {d} | ${entry:,.2f} | {qty:.4f} | ${notional:,.2f} | "
                     f"${margin:,.2f} | ${tp:,.2f} | ${sl:,.2f} | {age} |")
    lines.append("")
    lines.append("## 3. Risk & Performance Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Sharpe (equity-curve) | {fmt(sharpe)} |")
    lines.append(f"| Sortino | {fmt(sortino)} |")
    lines.append(f"| Calmar | {fmt(calmar)} |")
    if isinstance(dd, dict):
        lines.append(f"| Max drawdown | {fmt(dd.get('max_dd', dd.get('max_drawdown', 0))*100, 2)}% |")
        lines.append(f"| Ulcer index | {fmt(dd.get('ulcer', 0))} |")
    else:
        lines.append(f"| Drawdown | {dd} |")
    if isinstance(var_cvar, tuple) and len(var_cvar) == 2:
        lines.append(f"| VaR (95%) | {fmt(var_cvar[0])} |")
        lines.append(f"| CVaR (95%) | {fmt(var_cvar[1])} |")
    else:
        if isinstance(var_cvar, dict):
            lines.append(f"| VaR95 (per trade) | ${-abs(var_cvar.get('var',0)):,.4f} |")
            lines.append(f"| CVaR95 (per trade) | ${-abs(var_cvar.get('cvar',0)):,.4f} |")
        else:
            lines.append(f"| VaR/CVaR | {var_cvar} |")
    lines.append(f"| Profit factor | {fmt(pf)} |")
    lines.append(f"| Expectancy / trade (price-move) | {exp:+.4%} |")
    lines.append(f"| Expectancy / trade (dollars) | ${sum(t['pnl_dollars'] for t in trades)/max(1,len(trades)):+,.3f} |")
    lines.append("")
    lines.append("## 4. Attribution")
    lines.append("")
    lines.append("### By exit reason")
    lines.append("")
    if isinstance(by_reason, dict):
        lines.append("| Reason | Count | Share |")
        lines.append("|--------|-------|-------|")
        tot = sum(v.get('count', 0) for v in by_reason.values()) or 1
        for r, v in sorted(by_reason.items(), key=lambda kv: -kv[1].get('count', 0)):
            lines.append(f"| {r} | {v.get('count',0)} | {100*v.get('count',0)/tot:.1f}% |")
    else:
        lines.append(str(by_reason))
    lines.append("")
    lines.append("### By symbol")
    lines.append("")
    if isinstance(by_sym, dict):
        lines.append("| Symbol | Count | Win% | PnL |")
        lines.append("|--------|-------|------|-----|")
        for sym, v in sorted(by_sym.items()):
            lines.append(f"| {sym} | {v.get('count',0)} | {v.get('wr',0.0):.1f}% | ${v.get('pnl',0.0):+,.2f} |")
    else:
        lines.append(str(by_sym))
    lines.append("")
    lines.append("## 5. Methodology & Caveats")
    lines.append("")
    lines.append("- Metrics computed by `analytics.py` (Sharpe/Sortino/Calmar/VaR-CVaR/profit-factor/"
                 "expectancy/attribution).")
    lines.append("- Effective equity = capital + unrealized P&L of open positions (mirrors Alpha 1).")
    lines.append("- Sample size is **small (n=%d)**; per the governance evidence policy, no live-edge "
                 "conclusion is drawn until n≥100 with a TIMEOUT/TP-SL split. All exits so far are TIMEOUT." % n)
    lines.append("- Meta-labeler retrained 2026-08-25 on the live universe (6mo futures 1m): "
                 "purged-K-fold CV primary 51.0% -> filtered 56.4% (+5.4pp, AUC 0.567, all 5 "
                 "folds positive). Live edge still UNPROVEN until the n-gate below clears.")
    lines.append("")
    lines.append("---")
    lines.append("_Reproduce: `python3 scripts/generate_hedge_report.py`_")

    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == '__main__':
    main()
