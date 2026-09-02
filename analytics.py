#!/usr/bin/env python3
"""
Top-1% Quant Hedge Visibility Analytics
Implements risk, attribution, portfolio, regime, and health metrics
for Telegram visibility. Designed for both $100 (Alpha3 6-asset) and
$100k (Alpha1) ledgers. No look-ahead, 60s-granularity causal.

Integrates fixed quant_core components (Sharpe annualization, PSR/DSR
concepts) but fixes known bugs (MC Sharpe, hardcoded bases).

Usage: import analytics; analytics.get_risk_report(state_file)
"""
import json
import csv
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
import numpy as np

DATA_DIR = Path(__file__).resolve().parent / 'dry_data'

# ── helpers ──────────────────────────────────────────────────────────────
def _load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text())

def _load_trades(state_file: Path):
    s = _load_state(state_file)
    trades = s.get('trades', [])
    # also fallback to trades.csv for richer history
    csv_trades = state_file.parent / state_file.stem.replace('state','trades').replace('dry','dry_trades')
    # handle alpha3/alpha4 naming
    if 'alpha3' in str(state_file) or 'alpha4' in str(state_file):
        pref = 'alpha4' if 'alpha4' in str(state_file) else 'alpha3'
        csv_trades = DATA_DIR / f'{pref}_trades.csv'
    else:
        csv_trades = DATA_DIR / 'dry_trades.csv'
    return trades, s

def _pnl_series(trades):
    if not trades:
        return np.array([])
    return np.array([float(t.get('pnl_pct', 0)) for t in trades], dtype=float)

def _pnl_dollars(trades):
    if not trades:
        return np.array([])
    return np.array([float(t.get('pnl_dollars', 0)) for t in trades], dtype=float)

# ── RISK METRICS ─────────────────────────────────────────────────────────
def compute_sharpe(trades, annualization: float = None, equity_curve=None, equity_times=None) -> float:
    """Hedge-grade Sharpe: prefers daily equity returns (252 sqrt) over per-trade.
    Falls back to per-trade only if equity curve unavailable.
    Fixed: does NOT use np.std(permutation(n)) bug.
    """
    # Prefer equity curve daily Sharpe
    if equity_curve is not None and len(equity_curve) > 5 and equity_times is not None:
        try:
            # resample to daily last equity
            daily = {}
            for t, eq in zip(equity_times, equity_curve):
                day = t.date().isoformat()
                daily[day] = eq
            days_sorted = sorted(daily.items())
            if len(days_sorted) >= 3:
                eqs = [v for _, v in days_sorted]
                rets = [(eqs[i]/eqs[i-1]-1) for i in range(1, len(eqs)) if eqs[i-1]!=0]
                if len(rets) >= 2 and np.std(rets, ddof=1) > 0:
                    return float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(252))
        except Exception:
            pass
    # fallback per-trade
    pnls = _pnl_series(trades)
    if len(pnls) < 2:
        return 0.0
    mean = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    if std == 0 or np.isnan(std):
        return 0.0
    sharpe = mean / std
    if annualization:
        # cap annualization to avoid ±1000 blow-up (Wave6 lesson)
        ann_capped = min(annualization, 252*20)  # max 20 trades/day equivalent
        sharpe *= math.sqrt(ann_capped)
    return float(sharpe)

def compute_sortino(trades, target: float = 0.0, annualization: float = None) -> float:
    pnls = _pnl_series(trades)
    if len(pnls) < 2:
        return 0.0
    mean = np.mean(pnls)
    downside = pnls[pnls < target]
    if len(downside) == 0:
        return float('inf') if mean > target else 0.0
    dd = np.std(downside, ddof=1)
    if dd == 0 or np.isnan(dd):
        return 0.0
    sortino = (mean - target) / dd
    if annualization:
        sortino *= math.sqrt(annualization)
    return float(sortino)

def compute_calmar(trades, equity_curve=None) -> float:
    """Calmar = annualized return / maxDD. Equity curve derived from pnl if None."""
    if not trades:
        return 0.0
    pnls = _pnl_dollars(trades)
    # build equity if not provided
    if equity_curve is None:
        # assume $100 base if avg pnl < 100 else 100k heuristic, but prefer state base
        equity_curve = [100000.0]
        for p in pnls:
            equity_curve.append(equity_curve[-1] + p)
        equity_curve = np.array(equity_curve)
    else:
        equity_curve = np.array(equity_curve, dtype=float)
    if len(equity_curve) < 2:
        return 0.0
    total_ret = (equity_curve[-1] / equity_curve[0] - 1) if equity_curve[0] != 0 else 0
    # annualize by trade count: trades per year estimate ~ 365*24*60 / 60 = 8760 trades/year at 60s if continuous
    # Better: use actual time span from trades
    try:
        t0 = datetime.fromisoformat(trades[0].get('entry_time', trades[0].get('exit_time','')).replace('Z',''))
        t1 = datetime.fromisoformat(trades[-1].get('exit_time', trades[-1].get('entry_time','')).replace('Z',''))
        days = max((t1 - t0).total_seconds() / 86400, 1)
        ann_ret = (1 + total_ret) ** (365 / days) - 1 if total_ret > -1 else -1
    except:
        ann_ret = total_ret  # fallback
    # maxDD
    peak = np.maximum.accumulate(equity_curve)
    dd = (peak - equity_curve) / peak
    max_dd = float(np.max(dd)) if len(dd) else 0
    if max_dd == 0:
        return float('inf') if ann_ret > 0 else 0.0
    return float(ann_ret / max_dd)

def drawdown_stats(equity_curve, window: int = None):
    """Returns dict: max_dd, current_dd, max_duration_bars, avg_dd, ulcer
    Auto-detects ledger reset (drop >5% in one bar) to avoid legacy-regime
    compression (e.g., Alpha3 114 peak → 100 reset on 2026-08-23)."""
    if equity_curve is None or len(equity_curve) < 2:
        return {'max_dd':0.0,'current_dd':0.0,'max_duration':0,'avg_dd':0.0,'ulcer':0.0}
    eq = np.array(equity_curve, dtype=float)
    # detect reset: largest single-bar drop >5% signals new regime
    if len(eq) > 10:
        diffs = eq[1:] / eq[:-1] - 1
        resets = np.where(diffs < -0.05)[0]
        if len(resets) > 0:
            last_reset = resets[-1] + 1  # start after drop
            eq = eq[last_reset:]
            if len(eq) < 2:
                return {'max_dd':0.0,'current_dd':0.0,'max_duration':0,'avg_dd':0.0,'ulcer':0.0}
    # optional windowing for chart scale
    if window is not None and len(eq) > window:
        eq = eq[-window:]
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    max_dd = float(np.max(dd))
    current_dd = float(dd[-1])
    avg_dd = float(np.mean(dd[dd>0])) if np.any(dd>0) else 0.0
    # duration: longest consecutive bars underwater
    max_dur = cur_dur = 0
    for d in dd:
        if d > 1e-9:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0
    # ulcer index = RMS of drawdowns
    ulcer = float(np.sqrt(np.mean(dd**2)))
    return {'max_dd':max_dd,'current_dd':current_dd,'max_duration':max_dur,'avg_dd':avg_dd,'ulcer':ulcer}

def compute_var_cvar(trades, confidence: float = 0.95):
    """Historical VaR/CVaR on per-trade dollar PnL (negative tail)."""
    pnls = _pnl_dollars(trades)
    if len(pnls) < 5:
        return {'var':0.0,'cvar':0.0,'var_pct':0.0,'cvar_pct':0.0}
    sorted_pnl = np.sort(pnls)  # worst first
    idx = int((1 - confidence) * len(sorted_pnl))
    idx = max(0, min(idx, len(sorted_pnl)-1))
    var = float(-sorted_pnl[idx])  # positive loss number
    tail = sorted_pnl[:idx+1]
    cvar = float(-np.mean(tail)) if len(tail) else 0.0
    # pct versions on pnl_pct
    pnl_pcts = _pnl_series(trades)
    sp = np.sort(pnl_pcts)
    var_pct = float(-sp[idx])
    cvar_pct = float(-np.mean(sp[:idx+1])) if idx>=0 else 0.0
    return {'var':var,'cvar':cvar,'var_pct':var_pct,'cvar_pct':cvar_pct}

def volatility_metrics(trades):
    pnls = _pnl_series(trades)
    if len(pnls) < 2:
        return {'realized_vol':0.0,'ewma_vol':0.0,'vol_annualized':0.0}
    realized = float(np.std(pnls, ddof=1))
    # EWMA lambda 0.94
    lam = 0.94
    var = pnls[0]**2
    for r in pnls[1:]:
        var = lam * var + (1-lam) * r**2
    ewma_vol = float(math.sqrt(var))
    # annualized: assume ~8760 trades/year at 60s if continuous, but use 252*6.5*60/60? Use 8760*0.5 for ~50% duty (only when signal)
    # Use data-derived: trades per day from timestamps
    try:
        t0 = datetime.fromisoformat(trades[0].get('exit_time','').replace('Z',''))
        t1 = datetime.fromisoformat(trades[-1].get('exit_time','').replace('Z',''))
        days = max((t1 - t0).total_seconds()/86400, 1)
        trades_per_year = len(trades) / days * 365
        vol_ann = realized * math.sqrt(trades_per_year) if trades_per_year>0 else 0
    except:
        vol_ann = realized * math.sqrt(252*10)  # fallback 2520 trades/year
    return {'realized_vol':realized,'ewma_vol':ewma_vol,'vol_annualized':vol_ann}

def profit_factor(trades):
    pnls = _pnl_dollars(trades)
    if len(pnls)==0:
        return 0.0
    wins = pnls[pnls>0].sum()
    losses = -pnls[pnls<0].sum()
    if losses == 0:
        return float('inf') if wins>0 else 0.0
    return float(wins/losses)

def expectancy(trades):
    pnls = _pnl_series(trades)
    if len(pnls)==0:
        return 0.0
    wr = np.mean(pnls>0)
    avg_win = np.mean(pnls[pnls>0]) if np.any(pnls>0) else 0
    avg_loss = np.mean(pnls[pnls<0]) if np.any(pnls<0) else 0
    return float(wr*avg_win + (1-wr)*abs(avg_loss) + avg_loss)  # avg_loss negative, so net

# ── ATTRIBUTION ──────────────────────────────────────────────────────────
def attribution_by_symbol(trades):
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t.get('symbol','UNK')].append(t)
    out = {}
    for sym, ts in by_sym.items():
        pnls = _pnl_dollars(ts)
        out[sym] = {
            'count': len(ts),
            'pnl': float(np.sum(pnls)),
            'avg_pct': float(np.mean(_pnl_series(ts))) if ts else 0,
            'wr': float(np.mean(pnls>0)*100) if len(pnls) else 0,
            'pf': profit_factor(ts),
            'best': float(np.max(pnls)) if len(pnls) else 0,
            'worst': float(np.min(pnls)) if len(pnls) else 0,
        }
    return out

def attribution_by_reason(trades):
    by_r = defaultdict(list)
    for t in trades:
        by_r[t.get('reason','?')].append(t)
    out = {}
    for r, ts in by_r.items():
        pnls = _pnl_dollars(ts)
        out[r] = {
            'count': len(ts),
            'pnl': float(np.sum(pnls)),
            'wr': float(np.mean(pnls>0)*100) if len(pnls) else 0,
            'share': len(ts)/len(trades)*100 if trades else 0,
        }
    return out

def attribution_by_hour(trades):
    by_h = defaultdict(list)
    for t in trades:
        try:
            hr = datetime.fromisoformat(t.get('exit_time','').replace('Z','')).hour
            by_h[hr].append(t)
        except:
            continue
    out = {}
    for h in range(24):
        ts = by_h.get(h, [])
        if not ts:
            continue
        pnls = _pnl_dollars(ts)
        out[h] = {'count': len(ts), 'pnl': float(np.sum(pnls)), 'wr': float(np.mean(pnls>0)*100)}
    return out

def attribution_by_duration(trades):
    # duration = exit - entry in minutes, bucket
    buckets = {'<30m':[], '30-60m':[], '60-75m':[], '>75m':[]}
    for t in trades:
        try:
            e0 = datetime.fromisoformat(t.get('entry_time','').replace('Z',''))
            e1 = datetime.fromisoformat(t.get('exit_time','').replace('Z',''))
            mins = (e1-e0).total_seconds()/60
            if mins < 30: buckets['<30m'].append(t)
            elif mins < 60: buckets['30-60m'].append(t)
            elif mins <= 75: buckets['60-75m'].append(t)
            else: buckets['>75m'].append(t)
        except:
            buckets['60-75m'].append(t)
    out = {}
    for k, ts in buckets.items():
        if not ts: continue
        pnls = _pnl_dollars(ts)
        out[k] = {'count':len(ts),'pnl':float(np.sum(pnls)),'wr':float(np.mean(pnls>0)*100)}
    return out

# ── PORTFOLIO ────────────────────────────────────────────────────────────
def concentration_metrics(trades):
    by_sym = attribution_by_symbol(trades)
    if not by_sym:
        return {'hhi':0,'eff_n':0,'top_share':0}
    # HHI on count share
    total = sum(v['count'] for v in by_sym.values())
    shares = [v['count']/total for v in by_sym.values()]
    hhi = sum(s**2 for s in shares)
    eff_n = 1/hhi if hhi>0 else 0
    top = max(shares)*100 if shares else 0
    return {'hhi':float(hhi),'eff_n':float(eff_n),'top_share':float(top)}

def rolling_correlation_proxy(trades, window: int = 20):
    """Proxy: correlation of per-trade pnl streams by symbol using aligned index.
    For true time-series correlation need price bars; this gives execution overlap insight."""
    # Build per-symbol pnl list aligned by trade order index bucketed
    syms = sorted(set(t.get('symbol') for t in trades))
    if len(syms) < 2:
        return {'matrix': {}, 'mean_corr': 0.0}
    # Map symbol -> pnl series in trade order
    series = {s: [] for s in syms}
    for t in trades:
        for s in syms:
            series[s].append(float(t.get('pnl_dollars',0)) if t.get('symbol')==s else 0.0)
    # compute pairwise correlation where both had trades in window
    mat = {}
    corrs = []
    for i, a in enumerate(syms):
        for b in syms[i+1:]:
            x = np.array(series[a], dtype=float)
            y = np.array(series[b], dtype=float)
            # only consider trades where at least one is nonzero to avoid sparse 0 inflation
            mask = (x!=0) | (y!=0)
            xv = x[mask]
            yv = y[mask]
            if len(xv) < 5:
                corr = 0.0
            else:
                corr = float(np.corrcoef(xv, yv)[0,1]) if np.std(xv)>0 and np.std(yv)>0 else 0.0
                if np.isnan(corr): corr = 0.0
            mat[f"{a.replace('USDT','')}/{b.replace('USDT','')}"] = corr
            corrs.append(abs(corr))
    mean_corr = float(np.mean(corrs)) if corrs else 0.0
    return {'matrix': mat, 'mean_corr': mean_corr}

def factor_stub(trades):
    """Stubs for momentum/vol exposure until regime engine is built.
    Returns realized hit rates and timeout-dependence as vol proxy."""
    by_r = attribution_by_reason(trades)
    tp_rate = by_r.get('TP',{}).get('share',0)
    sl_rate = by_r.get('SL',{}).get('share',0)
    to_rate = by_r.get('TIMEOUT',{}).get('share',0)
    # vol proxy: high TIMEOUT = barriers decorative (low vol or wrong scale)
    regime_hint = "LOW_VOL/WRONG_SCALE" if to_rate > 80 else "BARRIERS_ACTIVE" if to_rate < 50 else "MIXED"
    return {'tp_rate':tp_rate,'sl_rate':sl_rate,'timeout_rate':to_rate,'regime_hint':regime_hint}

# ── HEALTH / RISK GOVERNANCE ────────────────────────────────────────────
# Thresholds recommended for $100 and $100k books (recommendation per user Q6)
RISK_THRESHOLDS = {
    'max_dd_warn': 0.05,      # 5% DD warning
    'max_dd_critical': 0.10,  # 10% critical
    'consecutive_losses_warn': 3,
    'sharpe_warn': 0.5,       # below 0.5 = no edge
    'pf_warn': 1.0,           # pf <1 = losing
    'var_daily_warn': 0.02,   # 2% per-trade VaR
    'ulcer_warn': 0.03,       # ulcer >3% = choppy DD
    'correlation_warn': 0.80, # mean abs corr >0.8 = over-concentrated
    'timeout_warn': 85,       # >85% timeout = barriers dead
}

def health_checks(state_file: Path):
    s = _load_state(state_file)
    trades = s.get('trades', [])
    equity = s.get('equity', s.get('capital', 100))
    peak = s.get('peak_equity', equity)
    dd = (peak - equity) / peak if peak else 0
    consec = s.get('consecutive_losses', 0)
    # need equity curve for ulcer + daily Sharpe
    eq_curve = None
    eq_times = None
    try:
        _pref = 'alpha4' if 'alpha4' in str(state_file) else ('alpha3' if 'alpha3' in str(state_file) else None)
        eq_csv = state_file.parent / (f'{_pref}_equity.csv' if _pref else 'dry_equity.csv')
        if eq_csv.exists():
            with open(eq_csv) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                # window to recent 80 already in drawdown_stats, but keep full for daily calc
                # Prefer effective_equity (capital + unrealized) when present, matching Alpha 1
                col = 'effective_equity' if 'effective_equity' in (reader.fieldnames or []) else 'equity'
                eq_curve = [float(r[col]) for r in rows]
                eq_times = [datetime.fromisoformat(r['time']) for r in rows]
    except:
        pass
    stats = drawdown_stats(eq_curve) if eq_curve else {'ulcer':0}
    pf = profit_factor(trades)
    # use daily Sharpe if possible
    sharpe = compute_sharpe(trades, equity_curve=eq_curve, equity_times=eq_times)
    var = compute_var_cvar(trades)
    corr = rolling_correlation_proxy(trades)
    by_r = attribution_by_reason(trades)
    timeout_rate = by_r.get('TIMEOUT',{}).get('share',0)

    alerts = []
    level = "OK"
    if dd >= RISK_THRESHOLDS['max_dd_critical']:
        alerts.append(f"🔴 CRITICAL DD {dd*100:.1f}% ≥10%")
        level = "CRITICAL"
    elif dd >= RISK_THRESHOLDS['max_dd_warn']:
        alerts.append(f"🟡 WARN DD {dd*100:.1f}% ≥5%")
        level = "WARN" if level=="OK" else level
    if consec >= RISK_THRESHOLDS['consecutive_losses_warn']:
        alerts.append(f"🟡 {consec} consecutive losses (CB {s.get('cooldown_remaining',0)} bars)")
        level = "WARN" if level=="OK" else level
    if pf < RISK_THRESHOLDS['pf_warn'] and len(trades)>=10:
        alerts.append(f"🟡 PF {pf:.2f} <1.0 (negative edge)")
        level = "WARN" if level=="OK" else level
    if sharpe < RISK_THRESHOLDS['sharpe_warn'] and len(trades)>=20:
        alerts.append(f"🟡 Sharpe {sharpe:.2f} <0.5 (no edge)")
        level = "WARN" if level=="OK" else level
    if stats['ulcer'] > RISK_THRESHOLDS['ulcer_warn']:
        alerts.append(f"🟡 Ulcer {stats['ulcer']*100:.1f}% choppy")
        level = "WARN" if level=="OK" else level
    if corr['mean_corr'] > RISK_THRESHOLDS['correlation_warn']:
        alerts.append(f"🟡 Corr {corr['mean_corr']:.2f} >0.80 concentration")
        level = "WARN" if level=="OK" else level
    if timeout_rate > RISK_THRESHOLDS['timeout_warn']:
        alerts.append(f"🟡 {timeout_rate:.0f}% TIMEOUT barriers decorative")
        level = "WARN" if level=="OK" else level

    return {'level':level,'alerts':alerts,'dd':dd,'pf':pf,'sharpe':sharpe,'ulcer':stats['ulcer'],'timeout_rate':timeout_rate}

# ── COMPOSITE REPORTS ────────────────────────────────────────────────────
def get_risk_report(state_file: Path):
    trades, state = _load_trades(state_file)
    eq_curve = None
    eq_times = None
    try:
        _pref = 'alpha4' if 'alpha4' in str(state_file) else ('alpha3' if 'alpha3' in str(state_file) else None)
        eq_csv = state_file.parent / (f'{_pref}_equity.csv' if _pref else 'dry_equity.csv')
        if eq_csv.exists():
            with open(eq_csv) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                col = 'effective_equity' if 'effective_equity' in (reader.fieldnames or []) else 'equity'
                eq_curve = [float(r[col]) for r in rows]
                eq_times = [datetime.fromisoformat(r['time']) for r in rows]
    except:
        pass
    # annualization: derive from trade duration but capped
    try:
        durs = []
        for t in trades:
            try:
                e0 = datetime.fromisoformat(t.get('entry_time','').replace('Z',''))
                e1 = datetime.fromisoformat(t.get('exit_time','').replace('Z',''))
                durs.append((e1-e0).total_seconds()/60)
            except: pass
        mean_dur = float(np.mean(durs)) if durs else 75.0
        trades_per_year = 525600 / mean_dur if mean_dur>0 else 8760
        ann = min(trades_per_year, 252*20)
    except:
        ann = 2000  # fallback

    sharpe = compute_sharpe(trades, annualization=ann, equity_curve=eq_curve, equity_times=eq_times)
    sortino = compute_sortino(trades, annualization=ann)
    calmar = compute_calmar(trades, eq_curve[-80:] if eq_curve and len(eq_curve)>80 else eq_curve)
    dd_stats = drawdown_stats(eq_curve)
    varc = compute_var_cvar(trades)
    vol = volatility_metrics(trades)
    pf = profit_factor(trades)
    exp = expectancy(trades)
    health = health_checks(state_file)

    return {
        'trades': len(trades),
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'dd_stats': dd_stats, 'var': varc, 'vol': vol,
        'pf': pf, 'expectancy': exp, 'health': health,
        'annualization': ann,
        'base': state.get('capital', 100 if ('alpha3' in str(state_file) or 'alpha4' in str(state_file)) else 100000),
        'equity': state.get('equity', 0),
        'peak': state.get('peak_equity', 0),
    }

def get_attribution_report(state_file: Path):
    trades, _ = _load_trades(state_file)
    return {
        'by_symbol': attribution_by_symbol(trades),
        'by_reason': attribution_by_reason(trades),
        'by_hour': attribution_by_hour(trades),
        'by_duration': attribution_by_duration(trades),
        'concentration': concentration_metrics(trades),
        'correlation': rolling_correlation_proxy(trades),
        'factor': factor_stub(trades),
        'total_trades': len(trades),
    }

def format_risk_telegram(report: dict, name: str = "Alpha") -> str:
    dd = report['dd_stats']
    var = report['var']
    vol = report['vol']
    h = report['health']
    # health emoji + status badge
    h_emoji = "🟢" if h['level']=="OK" else "🟡" if h['level']=="WARN" else "🔴"
    level_badge = {"OK": "✅", "WARN": "⚠️", "CRITICAL": "🛑"}[h['level']]

    # quality line: trades + key metrics
    quality = (f"📊 <b>Quality</b>  ({report['trades']} trades, ann×{report['annualization']:.0f})"
               f"\nSharpe {report['sharpe']:.2f}  Sortino {report['sortino']:.2f}  Calmar {report['calmar']:.2f}"
               f"\nPF {report['pf']:.2f}  Exp {report['expectancy']:+.2%}/trade")

    # drawdown compact
    dd_line = (f"📉 <b>Drawdown</b>"
               f"\nCur {dd['current_dd']*100:.2f}%  Max {dd['max_dd']*100:.2f}%  Avg {dd['avg_dd']*100:.2f}%"
               f"\nUlcer {dd['ulcer']*100:.2f}%  MaxDur {dd['max_duration']}b")

    # tail risk compact
    tail = (f"⚠️ <b>Tail Risk</b> (95%)"
            f"\nVaR ${var['var']:.2f} ({var['var_pct']*100:.2f}%)  CVaR ${var['cvar']:.2f} ({var['cvar_pct']*100:.2f}%)"
            f"\nVol {vol['realized_vol']*100:.2f}% (EWMA {vol['ewma_vol']*100:.2f}%) ann {vol['vol_annualized']*100:.1f}%")

    # health note with threshold reference
    # health note: show alerts if any, otherwise OK
    # NOTE: alert strings contain raw '<'/'>' (e.g. "Sharpe -0.07 <0.5") which is
    # invalid HTML for Telegram's parse; escape them so the message parses.
    esc = lambda s: (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
    alert_text = esc("  ".join(h['alerts'])) if h['alerts'] else "✅ All thresholds OK"
    health_note = f"🏥 <b>Health</b>: {h['level']} {level_badge} {alert_text}"

    lines = [
        f"{h_emoji} <b>{name} RISK DASHBOARD</b>",
        f"━━━━━━━━━━━━━━━━━",
        quality,
        dd_line,
        tail,
        health_note,
        f"━━━━━━━━━━━━━━━━━",
        f"<i>Thresholds: DD 5%/10%, PF 1.0, Sharpe 0.5, Ulcer 3%, Corr 0.80, TO 85%</i>",
    ]
    return "\n".join(lines)

def format_attribution_telegram(report: dict, name: str = "Alpha") -> str:
    by_sym = report['by_symbol']
    by_r = report['by_reason']
    conc = report['concentration']
    corr = report['correlation']
    factor = report['factor']
    lines = [
        f"📈 <b>{name} ATTRIBUTION</b>",
        f"━━━━━━━━━━━━━━━━━",
        f"🎯 <b>By Symbol</b> ({report['total_trades']} trades)",
    ]
    # Sort by PnL descending for most impact first
    for sym, v in sorted(by_sym.items(), key=lambda x: x[1]['pnl'], reverse=True):
        lines.append(f"  {sym.replace('USDT','')}: {v['count']}t PnL ${v['pnl']:+.2f} WR {v['wr']:.1f}% PF {v['pf']:.2f}")
    # Summary line
    total_pnl = sum(v['pnl'] for v in by_sym.values())
    lines.append(f"  ━━━  Total PnL: ${total_pnl:+.2f}  AvgWR: {np.mean([v['wr'] for v in by_sym.values()]):.1f}%")
    lines.append(f"")
    lines.append(f"🚪 <b>By Exit</b>")
    # Sort by share descending (most common exit first)
    for r, v in sorted(by_r.items(), key=lambda x: x[1]['share'], reverse=True):
        lines.append(f"  {r}: {v['count']}t ({v['share']:.1f}%) PnL ${v['pnl']:+.2f} WR {v['wr']:.1f}%")
    # Timeout regime hint as prominent line
    lines.append(f"Timeout hint: {factor['regime_hint']} (TO {factor['timeout_rate']:.0f}%)")
    lines.append(f"")
    if report['by_duration']:
        lines.append(f"⏱ <b>By Duration</b>")
        # Sort by win rate descending
        _esc = lambda s: s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        for k, v in sorted(report['by_duration'].items(), key=lambda x: x[1]['wr'], reverse=True):
            lines.append(f"  {_esc(k)}: {v['count']}t PnL ${v['pnl']:+.2f} WR {v['wr']:.1f}%")
        lines.append(f"")
    if report['by_hour']:
        # top 3 best performing hours
        hrs = sorted(report['by_hour'].items(), key=lambda x: x[1]['pnl'], reverse=True)
        lines.append(f"🕐 <b>By Hour (top)</b>")
        for h, v in hrs[:3]:
            lines.append(f"  {h:02d}:00 {v['count']}t ${v['pnl']:+.2f} WR {v['wr']:.1f}%")
        # also show worst hour for balance
        worst = sorted(report['by_hour'].items(), key=lambda x: x[1]['pnl'])[0]
        lines.append(f"  🔻 {worst[0]:02d}:00 {worst[1]['count']}t ${worst[1]['pnl']:+.2f} WR {worst[1]['wr']:.1f}%")
        lines.append(f"")
    if corr['matrix']:
        # show only top 3 strongest correlations with color indication
        top_corr = sorted(corr['matrix'].items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        corr_text = ", ".join([f"{p}: {c:+.2f}" for p, c in top_corr])
        lines.append(f"🔗 <b>Correlation</b>  (mean |{corr['mean_corr']:.2f}|)")
        lines.append(f"  Strongest: {corr_text}")
    lines.append(f"━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def format_exposure_telegram(state_file: Path, name: str = "Alpha") -> str:
    s = _load_state(state_file)
    trades, _ = _load_trades(state_file)
    open_pos = s.get('open_positions', {})
    base = s.get('capital', 100 if ('alpha3' in str(state_file) or 'alpha4' in str(state_file)) else 100000)
    equity = s.get('equity', base)
    stake_pct = s.get('stake_pct', 0.075 if ('alpha3' in str(state_file) or 'alpha4' in str(state_file)) else 0.03)
    lev = s.get('leverage', 50)
    cap_per_slot = stake_pct * lev
    # current exposure
    total_notional = 0
    lines = [
        f"💼 <b>{name} EXPOSURE</b>",
        f"━━━━━━━━━━━━━━━━━",
        f"Equity ${equity:,.2f} / Base ${base:,.2f}  Peak ${s.get('peak_equity',equity):,.2f}",
        f"Open: {len(open_pos)} positions",
    ]
    for sym, pos in open_pos.items():
        entry = pos.get('entry_price',0)
        qty = pos.get('quantity',0)
        notional = entry*qty
        total_notional += notional
        age = pos.get('age', len(pos.get('price_path',[]))-1)
        direction = pos.get('direction', 'long')
        d_emoji = '🟢' if direction == 'long' else '🔴'
        # calculate unrealized PnL vs current price
        current = pos.get('current_price', entry)  # will be filled by caller if available
        pnl_d = (current - entry) * qty if current and entry and qty else 0
        pnl_pct = (current - entry) / entry * 100 if entry and current and entry != 0 else 0
        lines.append(f"  {d_emoji} {sym.replace('USDT','')}: ${notional:,.0f} ({notional/equity*100:.1f}%) age {age}/75  "
                     f"${pnl_d:+.0f} ({pnl_pct:+.2f}%)")
    lines.append(f"Total Notional ${total_notional:,.0f} ({total_notional/equity*100:.1f}% of equity)")
    # leverage summary with cap annotation
    cap_annotation = f" (cap {stake_pct*100:g}% ×{lev:g}x → {cap_per_slot:.2f}x/slot)" if cap_per_slot != 50 else ""
    lines.append(f"Leverage: {total_notional/equity:.2f}x{cap_annotation}")
    # risk summary mini
    pf = profit_factor(trades)
    var = compute_var_cvar(trades)
    lines.append(f"📊 PF {pf:.2f}  VaR95 ${var['var']:.2f}  WR {s.get('total_wins',0)}/{s.get('total_trades',0)} ({s.get('total_wins',0)/max(s.get('total_trades',1),1)*100:.1f}%)")
    lines.append(f"CD {s.get('consecutive_losses',0)}  Cooldown {s.get('cooldown_remaining',0)} bars")
    lines.append(f"━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)
