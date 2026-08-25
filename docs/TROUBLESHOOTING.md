# Troubleshooting

**Scope.** Operational runbook for the Alpha 3 demo system. Each entry: symptom →
cause → fix. Assumes the deployment in `DEPLOY.md` is in place.

---

## 1. Bot "running" but zero trades
- **Symptom:** service active, equity flat, no open positions, no trade rows.
- **Cause (historical):** frozen `price_history` (append only when flat) froze the
  barrier path; the vertical barrier was dead code; SL PnL was negated.
- **Fix:** runner-side exit evaluation with a per-position live `price_path`;
  TIMEOUT handled when `len(path) >= H+1`; PnL booked by sign. Verify with:
  ```bash
  python3 -c "import json; s=json.load(open('dry_data/alpha3_state.json'));
  print('trades', len(s['trades']), 'open', len(s['open_positions']))"
  ```

## 2. Demo orders not filling (only 2 positions)
- **Symptom:** paper opens 6 positions, demo shows only 2.
- **Cause:** `place_limit_order` at the entry price rarely fills on a moving market.
- **Fix:** demo entry uses `place_market_order` (immediate fill at market).
  Confirm in `dry_data/alpha3_state.json` → `open_positions` matches paper count.

## 3. Leverage shows 20x instead of 50x
- **Symptom:** `getAccount` reports `leverage: 20`.
- **Cause:** Binance default; `set_leverage_all` not called at startup.
- **Fix:** runner calls `demo_trader.set_leverage_all(ALPHA3_ASSETS, 50)` on boot.
  Force: `python3 - <<'PY'
  import demo_trader as d, binance_config as c
  d.set_leverage_all(c.ALPHA3_ASSETS, 50)
  PY`

## 4. Equity CSV column mismatch
- **Symptom:** analytics/notify KeyError on `effective_equity`.
- **Cause:** older `alpha3_equity.csv` predates the `effective_equity` column.
- **Fix:** stop runner, `rm dry_data/alpha3_equity.csv`, restart; header is
  rewritten on first log. (Runtime state is untracked; safe to remove.)

## 5. Feature-index boundary mismatch (idx 199 vs 200)
- **Symptom:** feature parity test fails at the last bootstrap bar.
- **Cause:** runner `compute_meta_features` gates `idx < 199`; `meta_features`
  gates `idx < 200`.
- **Fix:** intentional and tested (documented in `test_meta_labeler.py`). Treat as
  expected; do not "align" blindly — it is load-bearing for parity.

## 6. Telegram bot not responding
- **Symptom:** `/status` returns nothing.
- **Cause:** `tg_bot_alpha2.py` depends on `notify` and `binance_config`; wrong
  `BOT_TOKEN`/chat allow-list, or `alpha3-dry-runner` not running.
- **Fix:** `journalctl --user -u alpha3-tg-bot -f`; verify token in `.env`;
  confirm runner service is active first.

## 7. Service crashes on import
- **Symptom:** `alpha3-dry-runner` exits immediately.
- **Cause:** missing `joblib`/`scikit-learn`, or `models/meta_labeler.joblib`
  absent/untracked.
- **Fix:** `pip install -r requirements.txt`; ensure model and metrics are present
  (committed). Re-run `python3 scripts/train_meta_labeler.py` if regenerating.

## 8. Kill switch engaged, can't reopen
- **Symptom:** `/status` shows `KILLED (cool)`; no new trades open.
- **Cause:** `kill_armed=True` (persisted in state) or `dry_data/alpha3_kill.flag`
  present. This is the intended post-trigger state.
- **Fix:** send `/disarm` (or `python3 alpha3_dry_runner.py --disarm`, or
  `make disarm`). Verify `kill_armed` clears in `/status`.

## 9. Open positions not closing on kill
- **Symptom:** `/kill` sent but a position remains open on demo-fapi.
- **Cause:** demo API error during `place_market_order(reduce_only=True)`, or
  `DEMO_LIVE=False` (runner not connected to demo). The local state is still
  cleared (`kill_armed=True`); the exchange side may need a manual close.
- **Fix:** check Telegram for `⚠️ Kill close <sym> failed`; manually close on
  demo-fapi; confirm `open_positions` empty in `alpha3_state.json`.

## 10. systemctl stop closed my positions
- **Symptom:** stopping the service flattened all demo positions.
- **Cause:** `FLATTEN_ON_SHUTDOWN=True` (default) — graceful shutdown flattens.
- **Fix:** expected/safe. To preserve positions on stop, set
  `FLATTEN_ON_SHUTDOWN=False` in `alpha3_dry_runner.py` (not recommended).
