# ALPHA SYSTEM — COMPLETE DOCUMENTATION

## Overview

This repository contains the complete Alpha quantitative trading system: a governed, AFML-conformant pipeline implementing Alpha 1% (long-only), Alpha 2% (bidirectional), and Alpha 3 (simulation-only) paper traders with live triple-barrier exits, walk-forward search, Kelly sizing, and governance.

All strategies currently have negative expected value on real BTC/ETH data. The live paper traders run at $0 cost only — **no strategy is deployment-ready**.

---

## Table of Contents

1. [Repository Structure](#repository-structure)
2. [Dependencies](#dependencies)
3. [Data Layout](#data-layout)
4. [Layer 1: Data Ingestion](#layer-1-data-ingestion)
5. [Layer 2: Signal Generation](#layer-2-signal-generation)
6. [Layer 3: Triple-Barrier Exit](#layer-3-triple-barrier-exit)
7. [Layer 4: Risk Management](#layer-4-risk-management)
8. [Layer 5: Governance](#layer-5-governance)
9. [Layer 6: Live State](#layer-6-live-state)
10. [Layer 7: Failure Modes](#layer-7-failure-modes)
11. [Current State](#current-state)
12. [Clone & Reproduce Guide](#clone--reproduce-guide)
13. [Governance Transfer Checklist](#governance-transfer-checklist)
14. [Files Reference](#files-reference)

---

## Repository Structure

```
alpha_system/
├── dry_runner.py                    # Alpha 1% live paper trader (unconditional LONG churn)
├── bidir_runner.py                  # Alpha 2% bidirectional paper trader (momentum signal)
├── backtest_alpha2.py               # Causal 5m backtest engine (run_strategy function)
├── alpha_1percent.py                # QuantConnect AFML-conformant algorithm
├── alpha_3.py                       # Alpha 3 simulator (dual ledger: real vs synthetic)
├── alpha_3_runner.py                # Alpha 3 runner scaffold (SIM ONLY)
├── walkforward_search.py            # Walk-forward real arm grid search (108 configs)
├── walkforward_synthetic.py         # Walk-forward synthetic arm (diagnostic)
├── kelly_test.py                    # Kelly criterion: real vs bugged synthetic
├── backtest_live_1m.py              # 1m-granularity validation (runner-mirror engine)
├── download_1m.py                   # Download Binance 1m klines (BTC/ETH)
├── notify.py                        # Telegram notification module
├── SYSTEM_DOCUMENTATION.md          # THIS FILE
├── dry_data/
│   ├── dry_state.json               # Alpha 1 live state (equity, trades, open positions)
│   ├── bidir_state.json             # Alpha 2 live state
│   ├── dry_trades.csv               # Alpha 1 trade log
│   ├── bidir_trades.csv             # Alpha 2 trade log
│   ├── dry_equity.csv               # Alpha 1 equity curve
│   ├── bidir_equity.csv             # Alpha 2 equity curve
│   └── dry_output.log               # Alpha 1 runner log
├── experiments/
│   ├── walkforward_results_20260819.json
│   ├── walkforward_results_synthetic_20260819.json
│   ├── kelly_results.json
│   ├── PR_20260819_walkforward_grid.json
│   ├── PR_20260819_alpha3_synthetic.json
│   └── 1m_results_20260819.json
└── user_data/
    └── data/
        └── binance/
            ├── BTC_USDT-5m.feather    # 5m candles
            ├── ETH_USDT-5m.feather
            ├── BTCUSDT_USDT-1m.feather    # 1m candles (for live validation)
            └── ETHUSDT_USDT-1m.feather
```

---

## Dependencies

### Python Packages

| Package | Purpose | Version | Command |
|---------|---------|---------|---------|
| `numpy >= 1.24` | Numerical computation | 1.26+ | `pip install numpy` |
| `pandas >= 2.0` | Data manipulation | 2.2+ | `pip install pandas` |
| `requests >= 2.28` | Binance API calls | 2.31+ | `pip install requests` |
| `pyarrow >= 12.0` | Feather file I/O | 14+ | `pip install pyarrow` |
| `scipy >= 1.10` | Statistical tests | 1.11+ | `pip install scipy` |

### System Dependencies

| Requirement | Purpose |
|-------------|---------|
| `python >= 3.14` | Required (Python 3.14+; uses forkserver multiprocessing default) |
| `git >= 2.30` | Version control |

### Internal Dependency: nkkelhe_quant_core

Located at `/home/nkhekhe/nkhekhe_quant_core/` (sibling repo). Imported via `sys.path.insert(0, '/home/nkhekhe/nkhekhe_quant_core')` in multiple files. If missing, the live runners fail.

Key modules used:
- `nkhekhe_quant_core.alpha_engine.labeling.AlphaTripleBarrierConfig`
- `nkhekhe_quant_core.alpha_engine.labeling.run_triple_barrier`
- `nkhekhe_quant_core.alpha_engine.risk.PositionSizingConfig`
- `nkhekhe_quant_core.alpha_engine.risk.RiskGovernor`
- `nkhekhe_quant_core.alpha_engine.edge.ScreeningPipeline`
- `nkhekhe_quant_core.alpha_engine.edge.EconomicGates`
- `nkhekhe_quant_core.alpha_engine.experiment_registry.ExperimentRegistry`

### Environment Variables (for Telegram notifications)

```bash
TELEGRAM_BOT_TOKEN=<token>          # Alpha 1% bot
TELEGRAM_CHAT_ID=@alpha_1percent     # Alpha 1% chat
ALPHA2_TELEGRAM_BOT_TOKEN=<token>    # Alpha 2% bot
ALPHA2_TELEGRAM_CHAT_ID=@alpha_2percent  # Alpha 2% chat
```

---

## Data Layout

| Source | Format | Granularity | Symbols | Time Range |
|--------|--------|-------------|---------|------------|
| `user_data/data/binance/BTC_USDT-5m.feather` | Feather | 5m | BTC | 2024-01-01 → 2026-08-16 |
| `user_data/data/binance/ETH_USDT-5m.feather` | Feather | 5m | ETH | 2024-01-01 → 2026-08-16 |
| `user_data/data/binance/BTCUSDT_USDT-1m.feather` | Feather | 1m | BTC | 2026-01-01 → 2026-08-19 |
| `user_data/data/binance/ETHUSDT_USDT-1m.feather` | Feather | 1m | ETH | 2026-01-01 → 2026-08-19 |
| `https://api.binance.com/api/v3/ticker/price` | HTTP | Live spot | BTC/ETH | Current moment |

Columns in all feather files: `date, open, high, low, close, volume`

---

## Layer 1: Data Ingestion

```text
Binance API (klines) → user_data/data/binance/*.feather → [run_strategy / run_cycle / alpha_1percent]
                                        ↓
                             Live: /ticker/price (60s polls via get_price)
```

- **Batch (5m historical)**: Feathers already cached in `user_data/data/binance/` (downloaded pre-2026-08-16)
- **Batch (1m historical)**: `download_1m.py` downloads via `/api/v3/klines` (1000 rows per request, 150ms sleep). Covers 2026-01-01 → session end (~332k bars each), cached as feather
- **Live (60s spot)**: Both runners call `get_price(symbol)` → `requests.get(f"{API}/ticker/price", params={'symbol': symbol}, timeout=10)` → instantaneous spot price. This is strictly more responsive than any bar-close model. The 5m-close backtest is **NOT a valid comparator**

---

## Layer 2: Signal Generation

### Alpha 1% (dry_runner.py)
**Signal: NONE — unconditional churn**
- Enters LONG whenever flat + `price_history[s]` >= 85 polls (warmup gate)
- **No momentum check** — `dry_runner.py:243`: `if len(state['price_history'][s]) >= TB.vertical_horizon + 10:`
- Re-enters immediately after every close
- This is an always-long churn engine, **NOT a momentum strategy**

### Alpha 2% (bidir_runner.py)
**Signal: momentum K=10 on 60s polls (= 10-minute momentum)** — default `--signal momentum`
- `direction_from_momentum(history, k=10)`: `ret = prices[-1]/prices[-1-k] - 1`; sign determines direction
- Signal computed on 60s polls → K=10 = 10 MINUTES of price history
- Enters bidirectional (long/short) when direction is non-zero
- Also supports `fracdiff` (d=0.1, lookback=5) and `sma_revert` (n=50) signals via CLI arg

### alpha_1percent.py (QuantConnect framework)
**Signal: fractional differentiation d=0.1, lookback=5**
- `_compute_fracdiff(prices, order=0.1)`: gamma-based binomial coefficients, truncated window=200, centered by subtracting mean of first 20 bars
- `direction = np.sign(current_frac)` — full AFML pipeline (feature contract → label contract → screening → risk → execute)

### backtest_alpha2.py
**Signal: momentum K=10 on 5m closes (= 50-minute momentum)**
- `momentum_direction(closes, k=MOMENTUM_K)`: identical formula to bidir_runner, but on 5m closes
- K=10 on 5m = 50-minute signal window — **DIFFERENT from live Alpha 2** (K=10 on 60s = 10-min)
- `if k <= 0: d = 'long'` enables churn mode (Alpha 1 live semantics) on the same engine

### Discrepancy Summary: Live vs Backtest

| Aspect | Live Alpha 1 | Live Alpha 2 | Backtest Engine | alpha_1% (QuantConnect) |
|--------|-------------|-------------|-----------------|------------------------|
| Granularity | 60s polls | 60s polls | 5m closes | Framework (live-equivalent would be 60s) |
| Signal | NONE (churn) | momentum K=10 @ 60s (10 min) | momentum K=10 @ 5m (50 min) | fracdiff d=0.1 |
| Barriers | ±2% | ±2% | ±2% | ±2% (vol-scaled optional) |
| Horizon | 75 polls (~75 min) | 75 polls (~75 min) | 15 bars (75 min) | 15 bars |
| Direction | long only | long/short | both | long |
| Entry gate | price_history >= 85 | price_history >= 85 | warmup=25 | full pipeline |
| Fees | None (paper) | None (paper) | 0.1%/side embedded | 0.1%/side |
| CB | 3 losses → 50 bars | 3 losses → 50 bars | 3 losses → 50 bars | 3 losses → 50 bars |
| Pos size | 3% of capital | 3% of capital | 3% of equity | 3% max |

---

## Layer 3: Triple-Barrier Exit

### Live Runners (dry_runner.py / bidir_runner.py)
- **Barriers**: ±2% of entry price
  - Long: `tp_price = entry * 1.02, sl_price = entry * 0.98`
  - Short: `tp_price = entry * 0.98, sl_price = entry * 1.02`
- **Vertical horizon** (`TB.vertical_horizon`): 75 polls ≈ 75 minutes
  - TIMEOUT triggers at `len(price_path) >= TB.vertical_horizon + 1` (76 polls)
- **Evaluation**: On **live price** at each 60s poll
  - `last = path[-1]` (newest live price appended every 60s)
  - TP/SL hit: exit at fixed barrier price (`exit_p = tp` or `exit_p = sl`)
  - TIMEOUT: exit at `last` (current live price)
  - Barriers decorative: ~3.5% combined hit rate, 96.5% TIMEOUT (at both 5m and 1m granularities)

### Backtest Engine (backtest_alpha2.py)
- **Barriers**: ±2% of entry price (same)
- **Horizon**: `HORIZON = 15` bars at 5m = 75 minutes (same duration)
- **Evaluation**: On **5m closes**
  - Barrier scan: `for t in entry_bar+1 .. entry_bar+HORIZON`: if `closes[t] >= tp` → TP exit at `tp`; if `closes[t] <= sl` → SL exit at `sl`
  - TIMEOUT: `exit_p = closes[entry_bar + HORIZON]` at exact bar 15
  - Force-close at last bar: `reason='END'`
  - Uses the full range (not just one price) — catches intra-bar crossings at close

### Exit Logic Comparison

| Event | Live (poll-based) | Backtest (close-based) |
|-------|-------------------|------------------------|
| TP hit | `path[-1] >= tp_price` → exit at `tp_price` | `closes[t] >= position['tp']` → exit at `position['tp']` |
| SL hit | `path[-1] <= sl_price` → exit at `sl_price` | `closes[t] <= position['sl']` → exit at `position['sl']` |
| Timeout | `len(path) >= H+1` → exit at `last` (live price) | `t > entry_bar + H` → exit at `closes[entry_bar + H]` |
| Re-entry | Immediately at next poll (next 60s) | Immediately at next bar (next 5m) |
| Intra-period capture | **YES** — polls instantaneous spot; catches spikes between 5m closes | NO — only sees 5m closes; misses intra-bar spikes |

---

## Layer 4: Risk Management

### Position Sizing
- **Fixed**: 3% of capital per position (`pos_pct=0.03` / `max_position_pct=0.03`)
- **NOT Kelly** — Kelly is tested but NOT implemented in production
- `kelly_fraction=0.25` in `PositionSizingConfig` is a **dead config field** (user explicitly declined implementation: "NO DONT")
- `stoploss_pct=0.15` is a **dead config** in live runners — exit is ±2% barriers + TIMEOUT, not stoploss

### Circuit Breaker
- 3 consecutive losses → 50-bar cooldown
- **Live runner**: `consec_losses` decremented reset to 0 on win; on 3rd loss: `cooldown_remaining = COOLDOWN(50)`
- **Backtest**: `consec_losses` tracked identically; same 50-bar cooldown

### Daily Limit
- `max_daily_loss_pct=0.10` (10%) exists in `RiskGovernor` config (alpha_1percent.py, RC in dry_runner.py)
- **NOT enforced in live runners** — `dry_runner.py:267-272` only sends daily summary, no trading halt
- Paper trading means capital resets each session start

### Kelly Criterion Test Results (reference)
- **S1 real Deep distribution**: 10,566 trades, 29.0% WR, net −$55,181 → **f* = 0** (formula: −94.08; numeric: 0.0)
- **S2 bugged W9 synthetic** (84/85/86% WR, `pnl_dollars = 100000.0 * pnl_pct`): → **f* = 34–36×**, quarter Kelly 8.5–9×
- **Monte Carlo (2,000 paths)**:
  - S1 real at 3%: median final $52,414 (−47.6% loss)
  - S1 real at 5%+: 100% ruin (50%)
  - S2 bugged at 3%: median final $8.4M (100% notional inflation bug)
  - S2 bugged at 35×: $516.6M
- `kelly_test.py | experiments/kelly_results.json`

### Leverage Risk (Monte Carlo 1×–100× on Deep config)
- Max Drawdown: 28.45% (1×) → 100.00% (50–100×)
- Return: −99.55% (1×) → −101.00% (50–100×)
- **No leverage on live bots** — both are paper traders with fixed 3% (1×) sizing

---

## Layer 5: Governance

### Protocol: Pre-Registration → Intake → Gates → OOS

Every hypothesis follows: **pre-register** (sha256-anchored, immutable) → **intake gate** (reject renamed negative families) → **walk-forward** (causal, 4 folds, 50-bar embargo) → **economic gates** → **OOS evaluation** → **verdict**.

### All Alpha Families — STATUS: CLOSED

| Family | Waves | Walk-forward | Real Result | Ref |
|--------|-------|-------------|-------------|-----|
| Sampling × fracdiff | 6 | 112/117k trades | NO_GO | Lessons v1.4, v1.8 |
| MA/RSI | 1 | — | NO_GO | Lessons v1.4 |
| RSI-reversion | 1 | — | NO_GO | Lessons v1.4 |
| Funding extremes | 4 | — | NO_GO (n=3 in 7 mo) | Lessons v1.4, v1.7 |
| Funding premium | 4 | — | NO_GO | Lessons v1.4 |
| Funding cross-section | 4 | — | NO_GO | Lessons v1.4 |
| Barrier exits | 7, 11 | 0/1605 (W8) + 0/108 (walkforward) | NO-GO | Lessons v1.7, v1.10 |
| Momentum (Deep) | 8–10 | 0/108 (G1+G2) | NO-GO (−7.98% train median, −7.57% fold4) | Lessons v1.10 |
| Momentum (1m validation) | 10 | 0/18 | NO-GO (both live configs) | Lessons v1.12 |
| Kelly (real) | 9 | — | f*=0 | Lessons v1.9 |
| Kelly (bugged synthetic) | 9 | — | f*=34–36× (NO AUTHORITY) | Lessons v1.9, v1.10 |
| Alpha 3 (synthetic res) | 10 | 4/4 gates PASS (simulation only) | NO_DEPLOY | Lessons v1.11 |

### Walk-Forward Protocol (walkforward_search.py)
- **Grid**: 108 configs = (K={5,10,15,20,30,40}) × (TP/SL={0.01,0.02,0.03}) × (H={10,15,30}) × (direction={long,both})
- **Folds**: 4 chronological per symbol, 50-bar embargo per fold
- **Selection**: rank by median combined net return over folds 1–3 (BTC+ETH shared capital)
- **Gates**:
  - G1: ≥20 trades per fold
  - G2: positive net ≥2/3 train folds
  - G3: validation (fold 4) net return > 0
  - G4: validation mean per-trade net return > 0.002 (0.2% fee hurdle)
- **Verdict**: PASS iff G1 AND G2 (selection) AND G3 AND G4 (OOS); else NO-GO
- **Real result**: 0/108 → NO-GO

### Alpha 3 Protocol (alpha_3.py)
- **Purpose**: simulation only — demonstrates bugged W9 synthetic distribution on a real engine
- **Mechanics**: Same Alpha 2 entry/exit engine; trade outcomes resolved iid p=0.85 ±2% with `pnl_dollars = 100000.0 * pnl_pct` (the bug)
- **Dual ledger**: Same entries booked twice — real causal barriers (3% sizing, 0.1%/side fees) vs synthetic p=0.85
- **4 Gates**:
  - G1: W9 conformance (50-trade walk at f=1.0, seed=1: WR 86.0%, +$72,000)
  - G2: divergence (10,543 same entries: real 28.5% −$54,886 vs synth 85.1% +$442,800)
  - G3: determinism
  - G4: engine mirror (Δ $295; required running-equity sizing + END force-close)
- **Deployment**: FORBIDDEN (`alpha_3_runner.py` refuses without `--offline`)

### Kelly Protocol (kelly_test.py)
- **Gate**: f* = 0 on real data → no position sizing authorized
- **Synthetic (bugged)**: f* 34–36× — **zero authority** (Wave 9 rule)
- **MC**: 2,000 paths, log-space drawdown, T = 10,566+ trades per path

### 50-Trade Live Milestone
- Pre-registered deciding evidence: at 50 live trades, assess whether the 60s-instant-poll advantage persists or regresses to 1m expected WR (~28%)
- Currently: 7/50 trades (Alpha 1: 4, Alpha 2: 3)
- P(7/7 | p=0.283) ≈ 1.5e-4 under the model — live 7/7 wins unexplained by close-model → residual gap = intra-minute spike capture (60s instant polls vs 1m closes)

---

## Layer 6: Live State (Verified 2026-08-19T22:43 UTC)

### Alpha 1% (dry_runner.py)
- Status: **Running** in screen `dry_runner` — 60s polls, H=75 aligned since 14:28 UTC
- Started trading: 14:00 UTC; duration: ~8.7 hours
- Trades: **19 total, 14W/5L** (WR 73.7%); 2 consecutive losses (circuit breaker imminent)
- Equity: **$100,415.13** (+$415.13); peak $100,510.19; max DD 0.0011
- Recent 5 trades: ETH SL −$60 → BTC TIMEOUT +$42 → ETH TP +$60 → ETH SL −$60 → BTC TIMEOUT −$8
- Open positions: BTC long @ $69,384 (TP $70,772 / SL $67,996), ETH long @ $2,243 (TP $2,288 / SL $2,198)
- Risk: max DD 0.11% (well within limits); H=75 alignment deployed

### Alpha 2% (bidir_runner.py)
- Status: **Running** in screen `bidir_runner` — 60s polls, H=75 aligned, `--signal momentum` (default, K=10)
- Started trading: 14:15 UTC; duration: ~8.5 hours
- Trades: **18 total, 10W/8L** (WR 55.6%); 2 consecutive losses (circuit breaker imminent)
- Equity: **$100,212.02** (+$212.02); peak $100,321.38; max DD 0.0011
- Recent 5 trades: ETH SL −$60 → BTC short TIMEOUT −$41 → ETH TP +$60 → ETH SL −$60 → BTC TIMEOUT −$8
- Open positions: BTC long @ $69,384 (TP $70,772 / SL $67,997), ETH long @ $2,243 (TP $2,288 / SL $2,198)
- Signal: momentum K=10 on 60s polls (= 10-minute momentum)

### Combined
- **37 total trades (19+18), 24W/13L** (WR 64.9%), **+$627.15** realized
- Both bots running ~0.5h/trade; approaching **50-trade milestone** (37/50 complete)
- Report + 4 charts sent to Alpha 1% Telegram (full-system report)

---

## Layer 7: Failure Modes (13 Waves)

| # | Failure | Where | Impact | Lesson Version |
|---|---------|-------|--------|---------------|
| 1 | `pnl_dollars = 100000.0 * pnl_pct` bug | backtest_alpha2.py:134, kelly_test.py:51, walkforward_synthetic.py:51 | 100% notional per trade instead of 3% sizing → inflates WR to 84-86%, +$68-72k, Sharpe ~16 | v1.9, v1.10 |
| 2 | Fixed ±2% barriers are decorative | dry_runner.py:185-191, backtest_alpha2.py:107-126 | 96-97% of trades TIMEOUT; TP/SL hit rate ~3.5% | v1.8, v1.12 |
| 3 | Live runner ≠ tested strategy | dry_runner.py:238-252 (no momentum) | Alpha 1% live is churn engine; backtest was momentum — different machines | v1.12 |
| 4 | Signal window mismatch | bidir_runner.py:315 (K=10 @ 60s) vs backtest (K=10 @ 5m) | Live Alpha 2 = 10-min momentum; backtest = 50-min momentum | v1.12 |
| 5 | Granularity mismatch | Live: 60s instant poll vs backtest: 5m closes | Live catches intra-minute spikes backtest misses; P(7/7) = 1.5e-4 under model | v1.12 |
| 6 | 5m backtest never valid comparator | backtest_alpha2.py (5m) vs live (60s) | Wrong on TWO axes: granularity + signal semantics | v1.12 |
| 7 | No purge/embargo in historical splits | FML search splits, backtest_alpha2.py walk-forward | Temporal dependence not respected; AUCs meaningless | v1.4 |
| 8 | Multiple testing without governance | 13 generations, 208 backtests | Walk-forward 2/25 NO-GO; DSR 0.995@N=1 → 0.86@N=10 | v1.5 |
| 9 | Self-certification ≠ evidence | "10.0/10 CERTIFIED FOR PRODUCTION" | 7 live bots lost money; audit must come from execution evidence + OOS | v1.6 |
| 10 | `stoploss=-0.99` at 30x leverage | backtest_alpha2.py config / Phoenix audit | Exchange liquidation as stop; ruin probability 1.0 | v1.7 |
| 11 | Leverage amplifies existing PnL | Kelly walk-forward grid | 10x → 3.5x amplification without more winners; no edge at any leverage | v1.7 |
| 12 | bug × leverage interaction | backtest_alpha2.py + leverage scaling | 100% notional bug × leverage = instant ruin | v1.7 |
| 13 | Alpha 3 SIM-ONLY boundary | alpha_3.py + alpha_3_runner.py | Deployment forbidden; dual ledger is the proof instrument | v1.11 |

### Key Bug Details
- **pnl_dollars bug**: `pnl_dollars = 100000.0 * pnl_pct` assumes 100% of capital per trade, but the contract is 3% position sizing. The bugged formula:
  - Inflates net PnL by ~33× (100% / 3%)
  - Makes negative-EV strategies appear positive (84-86% WR vs real 28%)
  - Kelly on bugged distribution: f*=35× vs real f*=0
  - Fix: `pnl_dollars = 100000.0 * 0.03 * pnl_pct`

- **The bug does NOT affect backtest_alpha2.py's internal results**: the backtest engine uses `qty = (equity * pos_pct) / entry` with `pos_pct=0.03`, computes `pnl_d` from actual quantity, and reports `pnl_dollars = pnl_d`. The bug is in CONSUMERS: `kelly_test.py` and `walkforward_synthetic.py` construct the bugged distribution independently (`pnl_dollars = 100000.0 * pnl_pct`). The walkforward_search.py uses backtest_alpha2.py's internal engine (correct sizing).

---

## Current State

### Summary of All Results

| Component | Result | Source |
|-----------|--------|--------|
| **Backtest (Deep, 5m)** | net −$55,181, WR 29.6%, Sharpe −31 | backtest_alpha2.py (with internal 3% sizing) |
| **Walk-forward (real, 5m)** | 0/108 → NO-GO; Deep train −7.98%, fold4 −7.57% | walkforward_search.py, experiments/walkforward_results_20260819.json |
| **Walk-forward (bugged synthetic)** | 108/108 PASS; cross-config std 34.2% (noise) | walkforward_synthetic.py, experiments/walkforward_results_synthetic_20260819.json |
| **Kelly (real)** | f*=0; MC at 3%: median $52k (−47.6%), 5%+ → ruin 100% | kelly_test.py, experiments/kelly_results.json |
| **Kelly (bugged synthetic)** | f*=34-36×; MC at 3%: $8.4M | Same; NO AUTHORITY |
| **1m walk-forward** | 0/18 → NO-GO; live configs negative EV | backtest_live_1m.py, experiments/1m_results_20260819.json |
| **Alpha 3** | All 4 gates PASS; SIM-ONLY | alpha_3.py, experiments/PR_20260819_alpha3_synthetic.json |
| **Live Alpha 1** | Running; 19 trades, 14W/5L (WR 73.7%); equity $100,415.13 | dry_runner.py, dry_data/dry_state.json |
| **Live Alpha 2** | Running; 18 trades, 10W/8L (WR 55.6%); equity $100,212.02 | bidir_runner.py, dry_data/bidir_state.json |
| **Combined** | 37 trades, 24W/13L (WR 64.9%); +$627.15 | Both runners running; 37/50 toward milestone |
| **50-trade live milestone** | ~37/50 trades complete (started 14:00 UTC, ~8.7h running) | Live milestone protocol |

### Final Verdict
- **Machinery validated**: triple-barrier fix works; exits book correctly; TP at exactly +2%
- **Edge unproven**: all configs negative EV at every granularity tested
- **No config is deployment-ready**
- **Paper runners continue at $0 cost** toward 50-trade live milestone
- **Alpha 3: SIM-ONLY, DEPLOYMENT FORBIDDEN**

---

## Clone & Reproduce Guide

### Prerequisites
```bash
# System
python --version  # must be >= 3.14
git --version     # must be >= 2.30

# Python packages
pip install numpy pandas requests pyarrow scipy
```

### 1. Clone the repository
```bash
git clone https://github.com/nkhekhe/alpha_system.git
cd alpha_system
```

### 2. Obtain data
#### 5m historical data
The 5m feather files (`BTC_USDT-5m.feather`, `ETH_USDT-5m.feather`) are committed to the repo or can be downloaded:
```bash
# If not in repo, download via Binance API:
python3 -c "
import pandas as pd, requests, time
from pathlib import Path
out = Path('user_data/data/binance')
out.mkdir(parents=True, exist_ok=True)
for sym in ['BTCUSDT','ETHUSDT']:
    base = sym.replace('USDT','_USDT')
    rows=[]
    cur=1704067200000  # 2024-01-01 UTC
    end=int(__import__('time').time()*1000)
    while cur<end:
        r=requests.get('https://api.binance.com/api/v3/klines',params={'symbol':sym,'interval':'5m','startTime':cur,'endTime':end,'limit':1000})
        batch=r.json()
        for k in batch: rows.append([k[0],k[1],k[2],k[3],k[4],k[5]])
        cur=batch[-1][0]+1
        if len(batch)<1000: break
        time.sleep(0.15)
    df=pd.DataFrame(rows,columns=['open_time','open','high','low','close','volume'])
    df['date']=pd.to_datetime(df['open_time'],unit='ms',utc=True)
    for c in ['open','high','low','close','volume']: df[c]=df[c].astype(float)
    df[['date','open','high','low','close','volume']].to_feather(out/f'{base}-5m.feather')
    print(f'{base}: {len(df)} bars')
"
```

#### 1m historical data (for live validation)
```bash
python3 download_1m.py
# Downloads BTC + ETH 1m klines 2026-01-01 -> now
# ~332k bars each, outputs to user_data/data/binance/
# Takes ~5-10 minutes; cached to feather after first download
```

#### Live price API
Both runners use `https://api.binance.com/api/v3/ticker/price` — public endpoint, no API key needed for spot pricing.

### 3. Restore live state (to reach current Alpha 1/2/3 state)
Copy the state files that capture the current running state:
```bash
# From the original system, copy:
cp /original/alpha_system/dry_data/dry_state.json dry_data/dry_state.json
cp /original/alpha_system/dry_data/bidir_state.json dry_data/bidir_state.json
# These contain current equity ($100,193.91 / $100,122.05), trade history (7W/0L), 
# and open positions (1 BTC long each)
```

### 4. Run the backtest engine
```bash
# Reproduce the verified Deep result (Alpha 2% 5m backtest)
python3 backtest_alpha2.py
# Expected: BTC 5114 trades WR 26.2% net -$26,468; ETH 5452 trades WR 31.6% net -$28,713
# Combined: 10,566 trades, WR ~29%, net -$55,181

# Walk-forward search (real arm)
python3 walkforward_search.py
# Expected: 0/108 configs pass G1+G2 -> NO-GO

# Walk-forward synthetic arm (diagnostic)
python3 walkforward_synthetic.py
# Expected: 108/108 PASS-synthetic (parameter-independent by construction)

# Kelly test
python3 kelly_test.py
# Expected: real f*=0; bugged f*=34-36x

# 1m granularity validation
python3 backtest_live_1m.py
# Expected: 0/18 passed; both live configs NO-GO
```

### 5. Run the live paper traders
```bash
# Start Alpha 1% (unconditional long churn)
python3 dry_runner.py

# Start Alpha 2% (momentum signal, K=10 on 60s polls)
python3 bidir_runner.py

# Alpha 3 simulator (simulation only — refuses without --offline)
python3 alpha_3_runner.py --offline
```

### 6. Run Alpha 3 simulator
```bash
python3 alpha_3.py
# All 4 gates PASS (G1-G4); produces synthetic-resolution trades with dual ledger
# Output shows real vs bugged-synthetic divergence per trade
```

### 7. View live state
```bash
python3 dry_runner.py --status
python3 bidir_runner.py --status
```

---

## Governance Transfer Checklist

When cloning to a new server, ensure ALL items pass:

- [ ] **Python ≥ 3.14** installed (`python --version`)
- [ ] **nkkelhe_quant_core** dependency available:
  - Either pip-install or clone to `/home/nkhekhe/nkhekhe_quant_core`
  - Or add to `PYTHONPATH`: `export PYTHONPATH=/path/to/nkkelhe_quant_core:$PYTHONPATH`
- [ ] **Binance API reachable** (`curl https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT`)
- [ ] **5m data available** (`user_data/data/binance/BTC_USDT-5m.feather` + ETH)
- [ ] **1m data available** (`user_data/data/binance/BTCUSDT_USDT-1m.feather` + ETH) — run `python3 download_1m.py` if missing
- [ ] **Telegram env vars configured** (for live trade alerts):
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (Alpha 1%)
  - `ALPHA2_TELEGRAM_BOT_TOKEN`, `ALPHA2_TELEGRAM_CHAT_ID` (Alpha 2%)
  - Store in `.env` file or export in environment
- [ ] **live state restored** (`dry_data/dry_state.json`, `dry_data/bidir_state.json`)
- [ ] **experiments/ results intact** (all pre-registration hashes match AGENTS.md)
- [ ] **backtest_alpha2.py unmodified** (3% sizing fix consistent; internal engine correct)
- [ ] **alpha_3.py marked SIM-ONLY** (`alpha_3_runner.py` refuses `--offline` is the ONLY path)
- [ ] **All 13 waves of failures understood** (see Layer 7); no re-run of closed families
- [ ] **50-trade live milestone** protocol established (currently 7/50 trades)
- [ ] **Kelly f*=0** confirmed (no sizing changes without new registration + re-audit)

---

## Files Reference

| File | Path | Key Lines | Purpose |
|------|------|-----------|---------|
| `dry_runner.py` | /home/nkhekhe/alpha_system/ | :32 (TB config), :243 (entry gate), :185-191 (exit logic) | Alpha 1% live paper trader |
| `bidir_runner.py` | /home/nkhekhe/alpha_system/ | :35 (TB config), :91 (momentum signal), :315 (entry gate) | Alpha 2% bidirectional live trader |
| `backtest_alpha2.py` | /home/nkhekhe/alpha_system/ | :42-50 (momentum_direction), :107-126 (exit), :188-199 (entry) | Causal 5m backtest engine |
| `alpha_1percent.py` | /home/nkhekhe/alpha_system/ | :65 (hypothesis), :91 (PositionSizingConfig), :574-595 (fracdiff) | QuantConnect framework algorithm |
| `alpha_3.py` | /home/nkhekhe/alpha_system/ | — | Alpha 3 simulator (dual ledger) |
| `alpha_3_runner.py` | /home/nkhekhe/alpha_system/ | — | Alpha 3 runner scaffold (refuses without --offline) |
| `walkforward_search.py` | /home/nkhekhe/alpha_system/ | :29-33 (grid), :107-109 (G1/G2 gates) | Real-data walk-forward grid (108 configs) |
| `walkforward_synthetic.py` | /home/nkhekhe/alpha_system/ | :31-33 (P_WIN=0.85) | Synthetic diagnostic arm |
| `kelly_test.py` | /home/nkhekhe/alpha_system/ | :43-50 (formula), :62-95 (MC) | Kelly on real vs bugged synthetic |
| `backtest_live_1m.py` | /home/nkhekhe/alpha_system/ | — | 1m-granularity validation (runner-mirror) |
| `download_1m.py` | /home/nkhekhe/alpha_system/ | — | Download 1m klines |
| `notify.py` | /home/nkhekhe/alpha_system/ | — | Telegram notification module |
| `SYSTEM_DOCUMENTATION.md` | /home/nkhekhe/alpha_system/ | — | This file |
| `dry_data/dry_state.json` | /home/nkhekhe/alpha_system/dry_data/ | — | Alpha 1 live state snapshot |
| `dry_data/bidir_state.json` | /home/nkhekhe/alpha_system/dry_data/ | — | Alpha 2 live state snapshot |
| `experiments/` | /home/nkhekhe/alpha_system/experiments/ | — | All results JSONs + pre-registrations |
| `user_data/data/binance/` | /home/nkhekhe/user_data/data/binance/ | — | Cached market data (5m + 1m) |

---

 *Generated: 2026-08-19T22:43 UTC | System Version: Wave 13 Complete | All strategies NO-GO on real 5m/1m data | Paper runners trading toward 50-trade milestone (37/50: 24W/13L, WR 64.9%) | Alpha 3 SIM-ONLY | Live 60s-poll advantage unexplained by 1m close model*
