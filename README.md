# Alpha Trading System

A governed, AFML-conformant quantitative trading codebase. Three strategies:

| Strategy | Engine | Market | Status |
|----------|--------|--------|--------|
| **Alpha 1%** (`dry_runner.py`) | Unconditional long churn | Mainnet **paper** | Running |
| **Alpha 2%** (`bidir_runner.py`) | Momentum K=10 bidirectional | Mainnet **paper** | Running |
| **Alpha 3%** (`alpha3_dry_runner.py`) | Momentum K=10 + **meta-labeler** filter | Demo-fapi **live hedge** (synthetic-resolution SIM) | Running |

> **GOVERNANCE VERDICT:** Every real-market backtest is **NO-GO** (0/108 walk-forward, Kelly f*=0, 1m 0/18). The meta-labeler is validated **only on Alpha 3's synthetic-resolution distribution (iid p=0.85)** — it demonstrates the *machinery*, not live edge. Alpha 3 is **SIMULATION ONLY — never deploy to real capital.**

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
│  Binance ticker/price (60s polls) + 1m klines                        │
│  Demo-fapi (https://demo.binance.com) for live hedge orders          │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 2: PRIMARY SIGNAL                                               │
│  momentum_direction(K=10): sign of 10-bar return                     │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 3: META-LABELER (Alpha 3 secondary filter)                      │
│  RF classifier → P(win). Enter only if P ≥ 0.50.                      │
│  Features: 36 at signal bar (momentum, vol, RSI, rollback, etc.)     │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 4: TRIPLE-BARRIER EXIT                                          │
│  TP/SL ±2% of entry | Vertical timeout at H=75                       │
│  Demo entry = MARKET order (mirrors paper fill)                      │
│  Demo exit  = MARKET order (TP/SL via bracket algo orders)           │
├──────────────────────────────────────────────────────────────────────┤
│ LAYER 5: RISK                                                         │
│  Stake 7.5% margin × 50x = $375/trade (compounding on $100)         │
│  Circuit breaker: 3 consecutive losses → 50-bar cooldown            │
│  Per-cycle meta-filter (not just entry): re-evaluates open logic     │
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
when P(win) ≥ threshold (default 0.50).

**Pipeline** (`scripts/`):

| Step | Script | Output |
|------|--------|--------|
| 1. Fetch history | `fetch_historical_klines.py` | `models/kline_data/*.csv` (1.56M bars, 6 assets × 259k 1m) |
| 2. Label | `generate_labels.py` | `models/labeled_signals.csv` (97,411 signals, 53.3% raw WR) |
| 3. Features | `engineer_features.py` | `models/labeled_features.csv` (36 features/signal) |
| 4. Train | `train_meta_labeler.py` | `models/meta_labeler.joblib` (purged K-fold CV) |
| 5. Validate | `validate_oos.py` | `models/oos_validation_results.json` (walk-forward) |
| 6. Runtime feats | `meta_features.py` | shared feature computation used by runner |

**Config** (`scripts/meta_labeler_config.py`) — matches runner exactly:
`K=10, H=75, TP_PCT=0.02, SL_PCT=-0.02, FEE_RATE=0.0002, PURGE=75, EMBARGO=75, RF 50 trees/max_depth 6`.

**Results:**
- Out-of-fold AUC **0.625**, Precision **63.3%** (vs 53.3% base rate)
- Walk-forward OOS: **Filtered WR 61.8% vs Raw 52.9% = +8.9pp**
- Selects ~44% of primary signals (filters out low-P ones)

> ⚠️ **Scope caveat:** these numbers are measured on Alpha 3's *synthetic-resolution*
> distribution (iid p=0.85 wins), not real markets. The meta-labeler is a correct,
> working instrument; its *edge* on live data is **unproven** (n=12 live trades, all TIMEOUT).

---

## Key Findings (governance logbook)

| Result | Value | Source |
|--------|-------|--------|
| 5m backtest (Deep) | net −$55,181, WR 29.6%, Sharpe −31 | `backtest_alpha2.py` |
| Walk-forward (real, 108 configs) | **0/108 → NO-GO** | `walkforward_search.py` |
| Kelly (real) | **f* = 0** (bet nothing) | `kelly_test.py` |
| 1m live-granularity validation | **0/18 → NO-GO** | `backtest_live_1m.py` |
| Meta-labeler OOS (synthetic) | Filtered 61.8% vs Raw 52.9% (+8.9pp) | `validate_oos.py` |
| Live Alpha 3 (demo hedge) | 12 trades, 83.3% WR (machinery PASS, edge UNKNOWN) | `alpha3_dry_runner.py` |

---

## Repo Layout

```
alpha_system/
├── alpha3_dry_runner.py      # Alpha 3 live runner (meta-labeler integrated)
├── dry_runner.py             # Alpha 1% mainnet paper
├── bidir_runner.py           # Alpha 2% mainnet paper
├── demo_trader.py            # Demo-fapi hedge order client (market + bracket)
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

Internal research. **All alpha strategies are NO-GO on real data. Alpha 3 is
simulation-only — never deploy to real capital.** Paper/live-hedge runners cost
$0 of real money by design.
