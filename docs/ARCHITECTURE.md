# Architecture

**Scope.** This document specifies the structure of the Alpha trading system: the
technology stack, the individual components and their internal drawings, the
unified system topology, the end-to-end signal-to-execution pipeline, and the
runtime wiring (import/control flow). It is the authoritative reference for how
the system is composed and how a trade is produced.

Companion images (rendered, reproducible):
- `docs/images/pipeline.png` — end-to-end pipeline with gate accept/reject and feedback loop.
- `docs/images/topology.png` — unified topology of the three strategies + shared components.

---

## 1. System Overview

The system runs three independent trading strategies and a shared observability
stack. All real-market strategies are **NO-GO**; Alpha 3 is a **simulation-only**
synthetic-resolution engine that also places **paper hedge orders** on Binance
demo-fapi (zero real capital at risk).

| Strategy | Entrypoint | Market | Signal | Edge status |
|----------|-----------|--------|--------|-------------|
| Alpha 1% | `dry_runner.py` | Mainnet **paper** | Unconditional long churn | Running, NO-GO on real |
| Alpha 2% | `bidir_runner.py` | Mainnet **paper** | Momentum K=10 bidir | Running, NO-GO on real |
| Alpha 3% | `alpha3_dry_runner.py` | Demo-fapi **live hedge** | Momentum K=10 + meta-labeler | Running, synthetic-only |

---

## 2. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Language | Python ≥ 3.11 (developed 3.14) | All runners, scripts, tooling |
| Numerical | numpy, pandas, scipy | Feature math, statistics |
| ML | scikit-learn, joblib | Random-Forest meta-labeler; model persistence |
| HTTP | requests | Binance public ticker + demo-fapi orders |
| Charts | matplotlib | Equity/trade charts, architecture images |
| Messaging | python-telegram-bot, python-dotenv | Alerts, command bot, config |
| Serialization | pyarrow (feather) | Backtest datasets |
| Process mgmt | systemd user units | Always-on, self-healing services |
| Config | `.env` + `binance_config.py` | Single source of truth for assets/keys |

---

## 3. Components and Internal Drawings

### 3.1 Alpha 1% — `dry_runner.py`
Mainnet **paper** runner. Unconditional long entries every cycle; triple-barrier
exit; equity tracked as `effective_equity` (capital + unrealized).

```
┌──────────────────────── dry_runner.py ────────────────────────┐
│  ticker/price (60s) ─▶ always LONG ─▶ TP/SL ±2% / TIMEOUT H   │
│        │                                                      │
│        ├─ log_equity(effective) ─▶ analytics ◀─ notify ─▶ @Nkhekhe_bot
│        └─ circuit breaker (3L → cooldown)                     │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Alpha 2% — `bidir_runner.py`
Mainnet **paper** runner. Momentum K=10 signal (long/short), triple-barrier exit.

```
┌──────────────────────── bidir_runner.py ─────────────────────┐
│  ticker/price (60s) ─▶ momentum-K10 ─▶ dir LONG/SHORT         │
│        │                                                      │
│        ├─ TP/SL ±2% / TIMEOUT H ─▶ log_equity ─▶ analytics    │
│        └─ notify ◀── @LetapataBot (legacy command interface)  │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Alpha 3% — `alpha3_dry_runner.py` (meta-labeler system)
The primary system documented here. Momentum primary signal **filtered** by a
trained Random-Forest meta-labeler; live demo-fapi hedge orders.

```
┌────────────────── alpha3_dry_runner.py ──────────────────────┐
│                                                                │
│  60s poll                                                     │
│    │                                                          │
│    ▼                                                          │
│  [bootstrap OHLCV 200×1m] ─▶ price_history                    │
│    │                                                          │
│    ▼                                                          │
│  momentum-K10 ──▶ primary direction (LONG/SHORT)              │
│    │                                                          │
│    ▼                                                          │
│  compute_meta_features(36) ──▶ meta_labeler.joblib            │
│    │                            │                             │
│    │                            ▼                             │
│    │                       P(win) ≥ 0.50 ?                    │
│    │                         │            │                   │
│    │                    PASS │            │ FAIL              │
│    │                         ▼            ▼                   │
│    │                  demo MARKET entry   META-FILTER (skip)  │
│    │                         │                               │
│    │                    bracket TP/SL                        │
│    │                         │                               │
│    ▼                         ▼                               │
│  triple-barrier monitor (60s): TP +2% / SL −2% / TIMEOUT H=75│
│    │                                                          │
│    ▼                                                          │
│  close (market) ─▶ realize PnL ─▶ equity + effective_equity  │
│    │                                                          │
│    └─▶ log_equity ─▶ analytics ─▶ notify ─▶ @LetapataBot     │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Hedge client — `demo_trader.py`
Thin Binance demo-fapi client. Signs requests (HMAC-SHA256), rounds quantities to
lot step, places market orders and bracket TP/SL, and sets leverage per symbol.

```
┌────────────────────── demo_trader.py ────────────────────────┐
│  _sign(params) ─ HMAC-SHA256(secret, querystring)             │
│  round_qty(symbol, qty) ─ floor to LOT_SIZE step              │
│  set_leverage_all(assets, 50) ─ POST /fapi/v1/leverage        │
│  place_market_order(side, qty)                                │
│  place_bracket_orders(side, qty, tp, sl)                      │
└──────────────────────────────────────────────────────────────┘
```

### 3.5 Configuration — `binance_config.py`
Single source of truth. Exposes `ALPHA3_ASSETS`, API base selection
(mainnet/testnet/demo), and key resolution. **All components import assets from
here** — no hard-coded symbol lists elsewhere.

### 3.6 Notification — `notify.py`
Telegram alerts (`send_message`, `notify_trade_open/close`, `notify_daily_summary`)
plus chart generation (`generate_equity_chart`, `generate_trade_chart`).

### 3.7 Analytics — `analytics.py`
Risk/performance library: `compute_sharpe/Sortino/Calmar`, `drawdown_stats`,
`compute_var_cvar`, `profit_factor`, `expectancy`, attribution by symbol/reason/
hour, `concentration_metrics`, `health_checks`. Consumed by the Telegram bot and
the hedge-report generator.

### 3.8 Command bot — `tg_bot_alpha2.py`
Long-polling Telegram interface for Alpha 3 (`@LetapataBot`): `/status`,
`/positions`, `/trades`, `/pnl`, `/equity`, `/tradechart`, `/risk`, `/health`,
plus `pause`/`resume`.

### 3.9 Meta-labeler pipeline — `scripts/`
Offline training pipeline (not part of the live loop):

```
fetch_historical_klines.py
        │  models/kline_data/*.csv  (1.56M bars)
        ▼
generate_labels.py        ─▶ models/labeled_signals.csv   (97,411)
        │
        ▼
engineer_features.py       ─▶ models/labeled_features.csv (36 feats)
        │
        ▼
train_meta_labeler.py      ─▶ models/meta_labeler.joblib  (purged K-fold)
        │
        ▼
validate_oos.py            ─▶ models/oos_validation_results.json
```

---

## 4. Unified System Topology

```
        ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
        │ ALPHA 1 %   │   │ ALPHA 2 %   │   │ ALPHA 3 %   │   │ TELEGRAM   │
        │ dry_runner  │   │ bidir_run   │   │ a3_runner  │   │ bots       │
        └─────┬──────┘   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘
              │                │                │                │
   ┌──────────┴────────────────┴────────────────┴────────────────┴──────────┐
   │  binance_config · demo_trader · analytics · notify · meta_labeler.joblib │
   └────────────────────────────────────────────────────────────────────────┘
              │                │                │                │
        ┌─────┴─────┐    ┌─────┴─────┐    ┌─────┴─────┐    ┌─────┴─────┐
        │  BINANCE   │    │ SYSTEMD   │    │  SCRIPTS   │    │  MODELS    │
        │ ticker+    │    │ services  │    │ meta-label │    │ .joblib    │
        │ demo-fapi  │    │ Restart=  │    │  pipeline  │    │ metrics    │
        │            │    │  always   │    │            │    │            │
        └────────────┘    └───────────┘    └────────────┘    └────────────┘
```

Rendered version: **`docs/images/topology.png`**.

---

## 5. End-to-End Pipeline (Signal → Gate → Buy/Sell → Feedback)

This is the core of Alpha 3. The meta-labeler is a **secondary gate** that
accepts or rejects the primary momentum signal before any order is placed.

```
 BINANCE 60s ticker
        │
        ▼
 OHLCV bootstrap (200×1m)
        │
        ▼
 momentum-K10 ──▶ direction (LONG / SHORT)
        │
        ▼
 compute 36 features ──▶ RF meta-labeler ──▶ P(win)
        │                                    │
        │                              P(win) ≥ 0.50 ?
        │                                │          │
        │                          PASS  │          │  FAIL
        │                            ▼          ▼
        │                      META-PASS   META-FILTER (reject)
        │                       ENTER          skip → next poll
        │                            │
        │                            ▼
        │                   demo MARKET entry + bracket TP/SL
        │                            │
        │                            ▼
        │            triple-barrier monitor (60s): TP +2% / SL −2% / TIMEOUT H=75
        │                            │
        │                            ▼
        │                   EXIT → realize PnL → equity + effective_equity
        │                            │
        │                            ▼
        │                   circuit breaker (3L → 50-bar cooldown)
        │                            │
        └──────────▶ equity log → analytics → Telegram (@LetapataBot)
                          │
                          └──▶ next 60s cycle (feedback loop)
```

Rendered version with annotated accept/reject branches and the feedback loop:
**`docs/images/pipeline.png`**.

**Gate behavior (observed).** In live operation the meta-labeler fires
`META-PASS` (~44% of primary signals) and `META-FILTER` for the rest; filtered
signals are re-evaluated on the next poll. Equity (realized) and
`effective_equity` (capital + unrealized) are both logged every cycle, closing the
feedback loop that drives risk state (cooldown, circuit breaker) into the next
cycle.

---

## 6. Wiring — Import and Control Flow

**Data/control edges (verified from source):**

| Consumer | Imports from | Use |
|----------|--------------|-----|
| `alpha3_dry_runner.py` | `notify` | `send_message` (alerts) |
| `alpha3_dry_runner.py` | `demo_trader` | `place_market_order`, `set_leverage_all`, `round_qty`, `cancel_algo_orders`, `place_bracket_orders` |
| `alpha3_dry_runner.py` | `binance_config` | `BINANCE_API_BASE`, `ALPHA3_ASSETS`, `USE_TESTNET` |
| `tg_bot_alpha2.py` | `notify` | `generate_equity_chart`, `generate_trade_chart` |
| `tg_bot_alpha2.py` | `binance_config` | assets, API base, demo keys |
| `analytics.py` | (standalone) | reads `alpha3_state.json` + `alpha3_equity.csv` |
| `scripts/*` | `meta_labeler_config` | shared constants |

**Cycle control flow (one poll):**

```
poll() → fetch ticker → update price_history
  → for each asset:
      if cooldown: decrement; continue
      if open position: evaluate triple-barrier; maybe close
      else: compute momentum → if signal: compute features → meta-labeler
            → if P≥threshold: open (market + bracket) else META-FILTER
  → update effective_equity → log_equity → maybe daily summary
  → sleep(60)
```

---

## 7. One-Trade Sequence (success path)

```
 t0  ticker poll            alpha3_runner
 t1  momentum-K10 = SHORT   primary signal
 t2  features[36] computed   compute_meta_features(idx=200)
 t3  model.predict_proba    → P(win)=0.62
 t4  P≥0.50 → META-PASS     enter
 t5  place_market_order(SELL, qty)   demo-fapi
 t6  place_bracket_orders(SELL, tp, sl)
 t7  state.open_positions[S] = {...}   notify "OPENED"
 t+H each 60s: barrier check
 t+75 or TP/SL: close(market) → PnL → equity += pnl
     notify "CLOSED" → log_equity → analytics
```

---

## 8. References
- `docs/GETTING_STARTED.md` — run it.
- `docs/GOVERNANCE.md` — process, verdicts, OEOS lessons.
- `docs/RESEARCH.md` — methodology and findings.
- `docs/PHD_HYPOTHESIS.md` — thesis + testable sub-hypothesis.
- `docs/HEDGE_REPORT.md` — quantitative hedge metrics (generated).
- `docs/TESTS.md` — test suite and coverage.
- `docs/TROUBLESHOOTING.md`, `docs/LEARNINGS.md`, `docs/RECOMMENDATIONS.md`, `docs/SWOT_ANALYSIS.md`, `docs/STORY.md`.
