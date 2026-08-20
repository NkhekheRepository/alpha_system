# Alpha Trading System

A governed, AFML-conformant quantitative trading pipeline implementing Alpha 1% (long-only paper churn), Alpha 2% (bidirectional paper trader with momentum signal), and Alpha 3% (simulation-only synthetic-resolution engine).

> **STATUS: All live strategies are NO-GO on real BTC/ETH data. Paper traders run at $0 cost only. No strategy is deployment-ready.**

## Quick Start

```bash
# 1. Clone
git clone https://github.com/nkhekhe/alpha_system.git
cd alpha_system

# 2. Setup (installs deps, downloads data, checks deps)
bash setup.sh

# 3. Run backtest
python3 backtest_alpha2.py

# 4. Start live paper traders
python3 dry_runner.py        # Alpha 1% (unconditional long churn)
python3 bidir_runner.py      # Alpha 2% (momentum K=10 signal)
python3 alpha_3_runner.py --offline  # Alpha 3% (simulation only)

# 5. Check status
python3 dry_runner.py --status
python3 bidir_runner.py --status
```

### Always-On (systemd, survives reboots)

```bash
# Install units (adjust paths if not /home/nkhekhe/alpha_system)
mkdir -p ~/.config/systemd/user
cp systemd/alpha1-dry-runner.service systemd/alpha2-bidir-runner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now alpha1-dry-runner.service alpha2-bidir-runner.service

# Require user services to start on boot without login
loginctl enable-linger $USER

# Status / logs
systemctl --user status alpha1-dry-runner alpha2-bidir-runner
journalctl --user -u alpha1-dry-runner -f
```

Both units use `Restart=always` (30s backoff, 10 bursts/600s limit) so the bots
self-heal on crash, and linger ensures they start at boot before any login.

### Telegram command bots

Two long-polling Telegram bots (`/status`, `/positions`, `/trades`, `/pnl`,
`/equity`, `/tradechart`) answer for each runner. Run them always-on too:

```bash
cp systemd/alpha1-tg-bot.service systemd/alpha2-tg-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now alpha1-tg-bot.service alpha2-tg-bot.service
# @Nkhekhe_bot  → Alpha 1%  (commands read dry_data/dry_state.json)
# @LetapataBot  → Alpha 2%  (commands read dry_data/bidir_state.json)
```

## Documentation

- Full system architecture: See `SYSTEM_DOCUMENTATION.md`
- Governance logbook: `../.config/opencode/AGENTS.md` (changelog v1.1–v1.12)

## Key Findings

| Result | Value | Source |
|--------|-------|--------|
| 5m backtest (Deep) | net −$55,181, WR 29.6%, Sharpe −31 | `backtest_alpha2.py` |
| Walk-forward (real, 108 configs) | **0/108 → NO-GO** | `walkforward_search.py` |
| Kelly (real) | **f* = 0** (bet nothing) | `kelly_test.py` |
| 1m live-granularity validation | **0/18 → NO-GO**; both live configs | `backtest_live_1m.py` |
| Walk-forward (bugged synthetic) | 108/108 PASS (diagnostic only) | `walkforward_synthetic.py` |
| Live Alpha 1 | 7W/0L, $100,193.91 | `dry_runner.py` |
| Live Alpha 2 | 3W/0L, $100,122.05 | `bidir_runner.py` |
| Alpha 3 | SIM-ONLY (4 gates PASS) | `alpha_3.py` |

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      LAYER 1: DATA                               │
│  Binance API (klines) → user_data/data/binance/*.feather          │
│  Live: /ticker/price (60s instantaneous polls)                  │
├──────────────────────────────────────────────────────────────────┤
│                      LAYER 2: SIGNAL                              │
│  Alpha 1: NONE (unconditional LONG churn)                        │
│  Alpha 2: momentum K=10 @ 60s (=10 min)                          │
│  Backtest: momentum K=10 @ 5m (=50 min)  ⚠️ MISMATCH               │
│  alpha_1%: fracdiff d=0.1 lookback=5                             │
├──────────────────────────────────────────────────────────────────┤
│                    LAYER 3: TRIPLE-BARRIER EXIT                   │
│  TP/SL: ±2% of entry  |  Vertical: H=75 (live) / H=15 (5m backtest)│
│  Barriers decorative: 96.5% TIMEOUT at every granularity        │
├──────────────────────────────────────────────────────────────────┤
│                     LAYER 4: RISK                                 │
│  Sizing: 3% position (NOT Kelly — f*=0)                          │
│  Stoploss=0.15% DEAD (exit = barriers + timeout)                 │
│  CB: 3 losses → 50-bar cooldown                                   │
├──────────────────────────────────────────────────────────────────┤
│                   LAYER 5: GOVERNANCE                             │
│  All 13 waves: NO-GO on real data; bugged synthetic trivially PASS│
│  50-trade live milestone: 7/50 complete                        │
│  Alpha 3: SIM-ONLY (dual ledger proof instrument)               │
└──────────────────────────────────────────────────────────────────┘
```

## Dependencies

See `requirements.txt`. Python 3.14+, `nkkelhe_quant_core` sibling repo.

## License

Internal use — all alpha strategies closed/NO-GO.
