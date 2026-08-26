# Alpha 3 Dry Mode — Quantitative Hedge Report

_Generated: 2026-08-26T02:17:38.611967 (UTC)_

> **DISCLAIMER:** Alpha 3 is a **simulation-only** system on the demo-fapi test account (real market prices, synthetic capital). Alpha 3 is **NO-GO on real capital** (see GOVERNANCE.md).

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Base capital | $100.00 |
| Realized equity | $124.86 |
| Effective equity (mark-to-market) | $125.24 |
| Unrealized P&L | $+0.38 |
| Total trades | 54 (30W / 24L) |
| Win rate | 55.6% |
| Open hedge positions | 5 |
| Total notional (open) | $2,575.44 |
| Total margin (open) | $128.77 |
| Leverage | 20x |

## 2. Hedge Book (live demo-fapi positions)

| Asset | Dir | Entry | Qty | Notional | Margin | TP | SL | Age |
|-------|-----|-------|-----|----------|--------|-----|-----|-----|
| STRKUSDT | long | $0.03 | 18552.6000 | $480.51 | $24.03 | $0.03 | $0.03 | 62 |
| ONGUSDT | long | $0.10 | 5000.0000 | $508.50 | $25.43 | $0.10 | $0.10 | 37 |
| TACUSDT | long | $0.00 | 185409.0000 | $503.01 | $25.15 | $0.00 | $0.00 | 34 |
| STXUSDT | long | $0.27 | 1973.0000 | $539.62 | $26.98 | $0.28 | $0.27 | 33 |
| HANAUSDT | long | $0.02 | 28651.0000 | $543.80 | $27.19 | $0.02 | $0.02 | 12 |

## 3. Risk & Performance Metrics

| Metric | Value |
|--------|-------|
| Sharpe (equity-curve) | 0.09 |
| Sortino | 0.25 |
| Calmar | 0.56 |
| Max drawdown | 0.00% |
| Ulcer index | 0.00 |
| VaR95 (per trade) | $-11.0900 |
| CVaR95 (per trade) | $-11.1900 |
| Profit factor | 1.13 |
| Expectancy / trade (price-move) | -0.0557% |
| Expectancy / trade (dollars) | $+0.461 |

## 4. Attribution

### By exit reason

| Reason | Count | Share |
|--------|-------|-------|
| TP | 21 | 38.9% |
| SL | 17 | 31.5% |
| TIMEOUT | 9 | 16.7% |
| KILL | 4 | 7.4% |
| RECONCILE | 3 | 5.6% |

### By symbol

| Symbol | Count | Win% | PnL |
|--------|-------|------|-----|
| BMTUSDT | 20 | 55.0% | $+13.45 |
| HANAUSDT | 6 | 66.7% | $+9.39 |
| ONGUSDT | 7 | 57.1% | $+2.64 |
| STRKUSDT | 6 | 66.7% | $+10.91 |
| STXUSDT | 6 | 66.7% | $+18.02 |
| TACUSDT | 9 | 33.3% | $-29.53 |

## 5. Methodology & Caveats

- Metrics computed by `analytics.py` (Sharpe/Sortino/Calmar/VaR-CVaR/profit-factor/expectancy/attribution).
- Effective equity = capital + unrealized P&L of open positions (mirrors Alpha 1).
- Sample size is **small (n=54)**; per the governance evidence policy, no live-edge conclusion is drawn until n≥100 with a TIMEOUT/TP-SL split. All exits so far are TIMEOUT.
- Meta-labeler retrained 2026-08-25 on the live universe (6mo futures 1m): purged-K-fold CV primary 51.0% -> filtered 56.4% (+5.4pp, AUC 0.567, all 5 folds positive). Live edge still UNPROVEN until the n-gate below clears.

---
_Reproduce: `python3 scripts/generate_hedge_report.py`_