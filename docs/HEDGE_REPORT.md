# Alpha 3 Dry Mode — Quantitative Hedge Report

_Generated: 2026-08-25T12:18:18.633075 (UTC)_

> **DISCLAIMER:** Alpha 3 is a **simulation-only** synthetic-resolution engine. All figures below describe the demo-fapi paper hedge book and the synthetic trade stream. Alpha 3 is **NO-GO on real capital** (see GOVERNANCE.md).

## 1. Executive Summary

| Metric | Value |
|--------|-------|
| Base capital | $112.31 |
| Realized equity | $112.31 |
| Effective equity (mark-to-market) | $109.21 |
| Unrealized P&L | $-3.10 |
| Total trades | 18 (13W / 5L) |
| Win rate | 72.2% |
| Open hedge positions | 2 |
| Total notional (open) | $826.33 |
| Total margin (open) | $16.53 |
| Leverage | 50x |

## 2. Hedge Book (live demo-fapi positions)

| Asset | Dir | Entry | Qty | Notional | Margin | TP | SL | Age |
|-------|-----|-------|-----|----------|--------|-----|-----|-----|
| XRPUSDT | long | $1.48 | 279.7000 | $415.07 | $8.30 | $1.51 | $1.45 | 41 |
| SOLUSDT | long | $98.86 | 4.1600 | $411.26 | $8.23 | $100.84 | $96.88 | 35 |

## 3. Risk & Performance Metrics

| Metric | Value |
|--------|-------|
| Sharpe (equity-curve) | 0.26 |
| Sortino | 0.26 |
| Calmar | 0.27 |
| Max drawdown | 5.90% |
| Ulcer index | 0.02 |
| VaR/CVaR | {'var': -0.0, 'cvar': -0.0, 'var_pct': 0.0167, 'cvar_pct': 0.0167} |
| Profit factor | 0.00 |
| Expectancy / trade | -0.00 |

## 4. Attribution

### By exit reason

| Reason | Count | Share |
|--------|-------|-------|
| TIMEOUT | 18 | 100.0% |

### By symbol

| Symbol | Count | Win% |
|--------|-------|------|
| BNBUSDT | 3 | 0.0% |
| BTCUSDT | 3 | 0.0% |
| ETHUSDT | 3 | 0.0% |
| SOLUSDT | 3 | 0.0% |
| XRPUSDT | 3 | 0.0% |
| ZECUSDT | 3 | 0.0% |

## 5. Methodology & Caveats

- Metrics computed by `analytics.py` (Sharpe/Sortino/Calmar/VaR-CVaR/profit-factor/expectancy/attribution).
- Effective equity = capital + unrealized P&L of open positions (mirrors Alpha 1).
- Sample size is **small (n=18)**; per the governance evidence policy, no live-edge conclusion is drawn until n≥100 with a TIMEOUT/TP-SL split. All exits so far are TIMEOUT.
- The meta-labeler is validated only on Alpha 3's synthetic-resolution distribution (iid p=0.85); its live edge is **UNPROVEN**.

---
_Reproduce: `python3 scripts/generate_hedge_report.py`_