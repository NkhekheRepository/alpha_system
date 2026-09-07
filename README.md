# Alpha Trading System

A governed, AFML-conformant quantitative trading codebase. Three strategies:

| Strategy | Engine | Market | Status |
|----------|--------|--------|--------|
| **Alpha 1%** (`dry_runner.py`) | Unconditional long churn | Mainnet **paper** | Running |
| **Alpha 2%** (`bidir_runner.py`) | Momentum K=10 bidirectional | Mainnet **paper** | Running |
| **Alpha 3%** (`alpha3_dry_runner.py`) | Momentum K=60 + **meta-labeler** filter | **Live USDT-M futures** (`fapi.binance.com`) on real capital | Running (LIVE) |

> **GOVERNANCE VERDICT:** Every real-market backtest is **NO-GO** (0/108 walk-forward, Kelly f*=0, 1m 0/18), and the meta-labeler is validated **only on Alpha 3's synthetic-resolution distribution (iid p=0.85)** — it demonstrates the *machinery*, not live edge. **Alpha 3 was nonetheless deployed to real capital on 2026-09-07 by explicit user directive** ($10, K60 H100 TP3%/SL1.5%, threshold 0.57) — see [`docs/adr/0004-live-K60H100-T0.57-10usd.md`](docs/adr/0004-live-K60H100-T0.57-10usd.md). Deployment proceeded with full knowledge of the NO-GO research verdict and is a live observation, not a validated strategy. Rollback (kill switch / testnet revert) documented in that ADR.

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [GETTING_STARTED.md](docs/GETTING_STARTED.md) | Run it on a fresh machine in a few steps |
| [DEPLOY.md](DEPLOY.md) | Full deployment reference |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System structure, topologies, pipeline, wiring + drawings |
| [GOVERNANCE.md](docs/GOVERNANCE.md) | Process, experimental ledger, deployment-block rules |
| [RESEARCH.md](docs/RESEARCH.md) | Methodology (AFML) and findings |
| [PHD_HYPOTHESIS.md](docs/PHD_HYPOTHESIS.md) | Thesis + testable sub-hypothesis + pre-registered gates |
| [HEDGE_REPORT.md](docs/HEDGE_REPORT.md) | Live quantitative hedge metrics (generated) |
| [TESTS.md](docs/TESTS.md) | Test suite coverage and how to run |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Operational runbook |
| [LEARNINGS.md](docs/LEARNINGS.md) | Engineering + quant lessons |
| [RECOMMENDATIONS.md](docs/RECOMMENDATIONS.md) | Prioritized next steps |
| [SWOT_ANALYSIS.md](docs/SWOT_ANALYSIS.md) | Strategic assessment |
| [STORY.md](docs/STORY.md) | Narrative: from 84% win rate to an honest machine |

Architecture images (rendered, reproducible): `docs/images/pipeline.png`,
`docs/images/topology.png`.

---

## ⚡ Quick Deploy (Alpha 3 Dry Mode)

For a fresh server, three commands get the full system running:

```bash
git clone https://github.com/nkhekhe/alpha_system.git
cd alpha_system
./deploy.sh            # installs deps, sets up systemd, copies .env template
```

Then fill keys and start:

```bash
nano .env              # add BINANCE_DEMO_API_KEY/SECRET + TELEGRAM token
systemctl --user enable --now alpha3-dry-runner.service alpha3-tg-bot.service
journalctl --user -u alpha3-dry-runner.service -f
```

Full detail in **[DEPLOY.md](DEPLOY.md)**.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ LAYER 1: DATA                                                          │
│  Binance ticker/price (10s polls) + 1m klines                        │
│  Live fapi (https://fapi.binance.com) for real orders (since ADR-0004)│
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 2: PRIMARY SIGNAL                                               │
│  momentum_direction(K=60): sign of 60-bar return                      │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 3: META-LABELER (Alpha 3 secondary filter)                      │
│  RF classifier → P(win). Enter only if P ≥ 0.57.                      │
│  Features: 36 at signal bar (momentum, vol, RSI, rollback, etc.)     │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 4: TRIPLE-BARRIER EXIT                                          │
│  TP/SL 3%/1.5% of entry | Vertical timeout at H=100                   │
│  Live entry = MARKET order (real capital, 20% margin × 20x)          │
│  Live exit  = MARKET (TP/SL/TIMEOUT via runner-side barrier eval)     │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 5: RISK                                                         │
│  Stake 20% margin × 20x = $40/trade (compounding on $10)             │
│  Circuit breaker: 3 consecutive losses → 50-bar cooldown            │
│  Per-cycle meta-filter re-evaluates entry                             │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 6: OBSERVABILITY                                                │
│  equity + effective_equity (capital + unrealized) log               │
│  Telegram alerts (@LetapataBot) + analytics.py dashboard            │
└──────────────────────────────────────────────────────────────────────┘
```

---

## The Meta-Labeler (Alpha 3)

López de Prado AFML secondary classifier. Primary signal = momentum direction;
meta-labeler predicts whether that signal will be a winner, and we only trade
when P(win) ≥ threshold (0.57 since 2026-09-07; 0.60 frequency-starved).

**Pipeline** (`scripts/`):

| Step | Script | Output |
|------|--------|--------|
| 1. Fetch history | `fetch_historical_klines.py` | `models/kline_data/*.csv` (1.56M bars, 10 assets × 259k 1m) |
| 2. Label | `generate_labels.py` | `models/labeled_signals.csv` (1,210,300 signals, 26.4% TP rate) |
| 3. Features | `engineer_features.py` | `models/labeled_features.csv` (36 features/signal) |
| 4. Train | `train_meta_labeler.py` | `models/meta_labeler.joblib` (purged K-fold CV) |
| 5. Validate | `validate_oos.py` | `models/oos_validation_results.json` (walk-forward) |
| 6. Runtime feats | `meta_features.py` | shared feature computation used by runner |

**Config** (`scripts/meta_labeler_config.py`) — matches runner exactly:
`K=60, H=100, TP_PCT=0.03, SL_PCT=-0.015, FEE_RATE=0.0005, PURGE=100, EMBARGO=100, RF 50 trees/max_depth 6`, universe 10 assets (+ZECUSDT), live threshold `0.57`.

**Results (2026-09-07 retrain, 1,195,647 rows):**
- Out-of-fold AUC **0.575** (up from 0.541)
- In-sample precision at live threshold `0.57`: **0.362** (sel 10.6%); breakeven at 2:1 RR + 0.05% fee = **34.4%**
- OOF precision ~0.32 (≈4pp below in-sample) — **below breakeven**; live frequency-starved at higher thresholds (0/9189 preds ≥ 0.60), hence threshold set to 0.57 for fills

> ⚠️ **Scope caveat:** the 0.575 AUC / 0.362 precision are in-sample retrain metrics on
> the synthetic-resolution bar/signal distribution (iid p=0.85 wins), not real markets.
> OOF precision is ~0.32 (below the 34.4% breakeven), and the K/H OOF grid
> (`scripts/search_kh_tp3_sl15.py`) was incomplete at deployment. Live is a
> **user-directed exception**, not a validated edge.

---

## Key Findings (governance logbook)

| Result | Value | Source |
|--------|-------|--------|
| 5m backtest (Deep) | net −$55,181, WR 29.6%, Sharpe −31 | `backtest_alpha2.py` |
| Walk-forward (real, 108 configs) | **0/108 → NO-GO** | `walkforward_search.py` |
| Kelly (real) | **f* = 0** (bet nothing) | `kelly_test.py` |
| 1m live-granularity validation | **0/18 → NO-GO** | `backtest_live_1m.py` |
| Meta-labeler OOS (synthetic) | Filtered 61.8% vs Raw 52.9% (+8.9pp) | `validate_oos.py` |
| Stress: clean sweep | 208 backtests, 16k+ grid rows — winners were selection artifacts | `scan/` |
| Live Alpha 3 (demo hedge) | 12 trades, 83.3% WR (machinery PASS, edge UNKNOWN) | `alpha3_dry_runner.py` |
| **Live Alpha 3 (real capital)** | **Deployed 2026-09-07 per ADR-0004** — $10, K60 H100 TP3/SL1.5%, T0.57, live fapi | `docs/adr/0004-live-K60H100-T0.57-10usd.md` |

---

## Repo Layout

```
alpha_system/
├── alpha3_dry_runner.py      # Alpha 3 live runner (meta-labeler integrated)
├── dry_runner.py             # Alpha 1% mainnet paper
├── bidir_runner.py           # Alpha 2% mainnet paper
├── demo_trader.py            # Live fapi order client (market + reduce-only close)
├── notify.py                 # Telegram alerts + equity chart
├── analytics.py              # Risk/sharpe/drawdown dashboard
├── binance_config.py         # API config + ALPHA3_ASSETS single source of truth
├── tg_bot_alpha2.py          # @LetapataBot command interface (Alpha 3)
├── scripts/                  # Meta-labeler pipeline (fetch→label→features→train→validate)
├── models/                   # Frozen model + metrics (committed)
│   ├── meta_labeler.joblib           # ← required to run without retraining
│   ├── meta_labeler_metrics.json
│   └── oos_validation_results.json
├── systemd/                  # User service units (alpha3-*.service)
├── docs/                      # Full documentation (see Documentation index)
│   └── images/                # Rendered architecture images (pipeline.png, topology.png)
├── tests/                     # 27-test automated suite (pytest)
├── pytest.ini                 # Test config (pythonpath=., testpaths=tests)
├── Makefile                   # make test / deploy / status
├── dry_data/                 # Runtime state (gitignored; regenerated on deploy)
├── requirements.txt
├── deploy.sh                 # One-command setup
├── .env.template             # Config template (copy to .env)
└── DEPLOY.md                 # Full deployment guide
```

---

## Operations

```bash
# Status
python3 alpha3_dry_runner.py --status

# Single cycle (no daemon)
python3 alpha3_dry_runner.py --stake 0.075 --leverage 50 --once

# Logs
journalctl --user -u alpha3-dry-runner.service -f

# Telegram commands (@LetapataBot): /status /positions /trades /pnl /equity /tradechart
#   Kill switch (human-in-the-loop): /kill (close all open trades once, then COOL) · /disarm (re-arm)
```

---

## Re-training the meta-labeler (optional)

The frozen model is committed, so retraining is **not required** to run. To retrain:

```bash
python3 scripts/fetch_historical_klines.py
python3 scripts/generate_labels.py
python3 scripts/engineer_features.py
python3 scripts/train_meta_labeler.py     # writes models/meta_labeler.joblib
python3 scripts/validate_oos.py
```

---

## License & Disclaimer

Internal research. **All alpha strategies are NO-GO on real backtest data.** Alpha 3
was nevertheless deployed to real capital on 2026-09-07 ($10, live fapi) by explicit
user directive under ADR-0004 — this is a live observation with OOF precision below
breakeven, not a validated edge. Paper/live-hedge runners cost $0 of real money by design.
