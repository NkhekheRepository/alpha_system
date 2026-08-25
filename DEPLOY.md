# Deploy Guide — Alpha 3 Dry Mode

Deploy the full Alpha 3 Dry Mode system (live demo-fapi hedge runner + Telegram
bot) on a fresh Linux server in **three commands**.

---

## Prerequisites

- Linux with `systemd` user services (most distros)
- Python **3.11+** (developed on 3.14)
- `pip`
- Binance **demo-fapi** keys — https://demo.binance.com (free, no real capital)
- A Telegram bot token (optional, for alerts/commands)

---

## Step 1–3: Clone + deploy

```bash
git clone https://github.com/nkhekhe/alpha_system.git
cd alpha_system
./deploy.sh
```

`deploy.sh` will:
1. Check Python ≥ 3.11
2. `pip install -r requirements.txt`
3. Create `dry_data/` and copy `.env.template` → `.env` (if missing)
4. Install systemd user units into `~/.config/systemd/user/`, rewriting paths to this repo
5. Verify `models/meta_labeler.joblib` is present
6. `systemctl --user daemon-reload`

---

## Step 4: Configure keys

```bash
nano .env
```

Fill in at minimum:

```ini
BINANCE_USE_TESTNET=true
BINANCE_DEMO_API_KEY=your_demo_key
BINANCE_DEMO_API_SECRET=your_demo_secret
ALPHA2_TELEGRAM_BOT_TOKEN=your_bot_token   # optional
ALPHA2_TELEGRAM_CHAT_ID=your_chat_id       # optional
```

Get demo keys at **https://demo.binance.com** → API Management.

---

## Step 5: Start services

```bash
systemctl --user enable --now alpha3-dry-runner.service
systemctl --user enable --now alpha3-tg-bot.service

# Start at boot without login (optional but recommended)
loginctl enable-linger $USER
```

---

## Step 6: Verify

```bash
# Watch live logs (you should see BOOTSTRAP, then META-PASS / META-FILTER)
journalctl --user -u alpha3-dry-runner.service -f

# Status snapshot
python3 alpha3_dry_runner.py --status
```

Expected first-cycle behavior:
- `BOOTSTRAP START <asset> (200 bars)` for each of 6 assets
- `META-PASS <asset>: prob=X >= 0.5 — ENTER` (or `META-FILTER` when prob < 0.5)
- `OPENED <asset>: SHORT @ $...` with TP/SL/timestamp
- `📡 Demo open <asset>: SELL <qty> @ market`

---

## What gets deployed

| Component | File | Notes |
|-----------|------|-------|
| Live runner | `alpha3_dry_runner.py` | `--stake 0.075 --leverage 50` |
| Telegram bot | `tg_bot_alpha2.py` | `@LetapataBot` command interface |
| Hedge client | `demo_trader.py` | Demo-fapi market + bracket orders |
| Meta-labeler | `models/meta_labeler.joblib` | Frozen, committed — no training needed |
| Config | `binance_config.py` | `ALPHA3_ASSETS` = BTC/ETH/SOL/BNB/XRP/ZEC |

---

## Reset / clean state

The runner state lives in `dry_data/alpha3_state.json`. To reset:

```bash
systemctl --user stop alpha3-dry-runner.service
rm -f dry_data/alpha3_state.json dry_data/alpha3_equity.csv dry_data/alpha3_trades.csv
systemctl --user start alpha3-dry-runner.service
```

---

## Run without systemd (foreground)

```bash
python3 alpha3_dry_runner.py --stake 0.075 --leverage 50
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `models/meta_labeler.joblib MISSING` | Retrain (see README) or copy the model file in |
| Only 2 of 6 demo positions open | Demo uses **MARKET** entry orders; ensure not on LIMIT (old bug) |
| Demo leveraging 20x not 50x | Runner now calls `set_leverage_all` at startup; verify keys valid |
| `effective_equity` column missing in chart | Delete old `alpha3_equity.csv`; it regenerates with new header |
| Bootstrapping every cycle | Fixed: bootstrap triggers at `< 200` bars, not `< 201` |

---

## Files committed (so a clone is runnable)

- All source (`*.py`, `scripts/`, `systemd/`)
- `models/meta_labeler.joblib` + `meta_labeler_metrics.json` + `oos_validation_results.json`
- `requirements.txt`, `deploy.sh`, `.env.template`, `README.md`, this file

**Not committed** (regenerated / secret): `.env`, `dry_data/*.json|csv`,
`models/kline_data/`, `models/labeled_*.csv` (training intermediates).
