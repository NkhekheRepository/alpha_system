# Alpha 3% Live Baseline — default state (2026-09-03)

This is the known-good live configuration. A fresh setup MUST reproduce
everything below. Tag: `alpha3-live-baseline-2026-09-03`.

## Mode
- `BINANCE_USE_LIVE=true`, `TRADING_MODE=live`, `BINANCE_USE_TESTNET=false`
- Service env: `BINANCE_DEMO_LIVE=true` (routes `demo_trader` to live fapi)
- Venue: live USDT-M futures (`https://fapi.binance.com`) + testnet mirrors

## Strategy (alpha3_dry_runner.py)
- Momentum K=30, H=100, WARMUP=110, 10s polls
- TP +3.5% / SL -2% / TIMEOUT bar 100 (market exits)
- 20% stake × 20x leverage (BICOUSDT 10x override), 0.02% fee assumption
- Circuit breaker: 3 consecutive losses → 50-bar entry-only cooldown
- Meta-labeler: K30 artifact, threshold 0.50, **36-feature inference**
  (`features_to_model_array`; the 10 live-only orderbook keys are excluded)
- Exit-sync: mandatory reduce-only live close on every TP/SL/TIMEOUT +
  mandatory Telegram receipt; boot reconcile + 60-cycle periodic orphan sweep
- `FLATTEN_ON_SHUTDOWN=true` — every stop/restart closes all live legs

## Model artifact
- `models/meta_labeler.joblib` md5: `c0c4557a34a637fa30ba34ac686512ae`
- Trained 2026-09-03 on 528,523 K30 labels, OOF AUC 0.590
- Pinned copies: `models/backup_k30/` (this baseline), `models/backup_k10/`

## Units (user)
- ENABLED + running: `alpha3-dry-runner`, `alpha3-tg-bot`, `reconcile-demo`
- DISABLED (Alpha 4 must never revive onto this wallet):
  `alpha4-dry-runner`, `alpha4-tg-bot`, `reconcile-alpha4`
- Alpha 1/2 + heartbeat: disabled, inactive

## Fixes baked into this baseline
1. Exit close dedented out of `except` (was dead on success path)
2. `sign_query` secret fix in `demo_trader` (reads returned 0 → closes no-op'd)
3. Reconcile `testnet` NameError + periodic sweep + unmasked per-venue reports
4. 36-column inference (ob-NaN silent veto + 46-vs-36 shape fault removed)
5. `compute_orderbook_features_at_index` import; tg-bot config import fix

## Restore path (fresh machine)
1. Clone repo, checkout tag `alpha3-live-baseline-2026-09-03`
2. Write `.env` with live keys + `BINANCE_USE_LIVE=true`,
   `TRADING_MODE=live`, `BINANCE_USE_TESTNET=false` (never commit `.env`)
3. `systemctl --user enable --now alpha3-dry-runner alpha3-tg-bot`
4. Confirm boot log: `Meta-labeler: LOADED (threshold=0.50, features=36)`,
   `Binance: MAINNET`, then `META-PASS`/`META-FILTER` on entries and
   `LIVE CLOSE … flattened` on exits

## Ledger note
Paper ledger (`dry_data/alpha3_state.json`) is session state, NOT part of
this baseline — resets start from CAP=$10; running equity is preserved
across restarts except flatten-on-shutdown closes.
