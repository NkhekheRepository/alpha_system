# Getting Started

**Scope.** Bring the Alpha 3 demo system from zero to running on a fresh machine
in a few steps. This is the operator's entry point; `DEPLOY.md` is the full
reference, `ARCHITECTURE.md` the structure.

---

## Prerequisites

- Linux with `systemd --user` available (or run manually).
- Python ≥ 3.11.
- Binance **demo-fapi** API key + secret (paper only; zero real capital).
- Telegram bot token + your chat id (alerts/commands).

---

## Steps

```bash
# 1. Clone / copy the repo
cd /opt
# (copy alpha_system/ to this machine, or git clone)

# 2. Create venv + install
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configure secrets (never commit .env)
cp .env.template .env
nano .env        # set BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET,
                #       TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_IDS

# 4. Verify tests are green (sanity gate)
python3 -m pytest -q

# 5. Deploy (systemd services)
./deploy.sh

# 6. Confirm
systemctl --user status alpha3-dry-runner
systemctl --user status alpha3-tg-bot
```

---

## First Validation

```bash
# Live state snapshot
python3 -c "import json; s=json.load(open('dry_data/alpha3_state.json'));
print('equity', s['equity'], 'effective', s.get('effective_equity'),
      'trades', len(s['trades']), 'open', len(s['open_positions']))"

# Regenerate the quantitative hedge report
python3 scripts/generate_hedge_report.py
# -> docs/HEDGE_REPORT.md

# Telegram
# send /status to your bot
```

---

## Re-running the Meta-Labeler (optional, offline)

```bash
python3 scripts/fetch_historical_klines.py
python3 scripts/generate_labels.py
python3 scripts/engineer_features.py
python3 scripts/train_meta_labeler.py
python3 scripts/validate_oos.py
```

This regenerates `models/meta_labeler.joblib` + `models/*_validation_results.json`
from 1.56M bars. Not required for the live demo (model is committed).

---

## Stop / Restart

```bash
systemctl --user stop  alpha3-dry-runner
systemctl --user start alpha3-dry-runner
journalctl --user -u alpha3-dry-runner -f   # live logs
```

---

## Next Reads
- `DEPLOY.md` — full deployment reference.
- `ARCHITECTURE.md` — system structure & pipeline.
- `GOVERNANCE.md` / `RESEARCH.md` / `PHD_HYPOTHESIS.md` — process, method, hypothesis.
- `HEDGE_REPORT.md` — live quantitative metrics.
- `TROUBLESHOOTING.md` — runbook.
