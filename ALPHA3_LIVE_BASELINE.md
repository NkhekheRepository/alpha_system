# Alpha 3% Live Baseline — default state (2026-09-12)

This is the known-good live configuration. A fresh setup MUST reproduce
everything below. Tag: `alpha3-live-baseline-2026-09-12`.

## Mode
- `BINANCE_USE_LIVE=true`, `TRADING_MODE=live`, `BINANCE_USE_TESTNET=false`
- Service env: `BINANCE_DEMO_LIVE=true` (routes `demo_trader` to live fapi)
- Venue: live USDT-M futures (`https://fapi.binance.com`) + testnet mirrors

## Strategy (alpha3_dry_runner.py)
- Momentum K=60, H=100, WARMUP=110, 10s polls
- TP +3% / SL -1.5% / TIMEOUT bar 100 (market exits)
- 20% stake × 20x leverage, 0.05% taker fee per fill = 0.10% round-trip
- Universe (48): TRIAUSDT, QUSDT, MAGMAUSDT, TRADOORUSDT, APRUSDT, UAIUSDT, DOODUSDT, BULLAUSDT, JCTUSDT, ZECUSDT, RAYSOLUSDT, XRPUSDT, BTCUSDT, ETHUSDT, SOLUSDT, KOMAUSDT, VTHOUSDT, IOSTUSDT, BEATUSDT, OPENAIUSDT, SNXUSDT, SUIUSDT, XLMUSDT, PUMPUSDT, 1000PEPEUSDT, BMTUSDT, EIGENUSDT, HEIUSDT, LINKUSDT, RENDERUSDT, ROSEUSDT, XVGUSDT, ANTHROPICUSDT, HYPEUSDT, CRVUSDT, DASHUSDT, ARBUSDT, INJUSDT, DOGEUSDT, UNIUSDT, JUPUSDT, XMRUSDT, TAOUSDT, REZUSDT, FLOCKUSDT, ZESTUSDT, PONSUSDT, MARSCOINUSDT
- MAX_OPEN_POSITIONS = 3 (cap concurrent positions; 20% × 20x each)
- Circuit breaker: 3 consecutive losses → 50-bar entry-only cooldown
- Meta-labeler: K60 artifact, threshold 0.61, **36-feature inference**
  (`features_to_model_array`; the 10 live-only orderbook keys are excluded)
- Orderbook history cap: 25 snapshots/symbol (latency optimization; full depth
  snapshots were the multi-MB state bloat slowing Telegram reads; live inference
  uses only the 36 OHLCV features at `FEATURE_ORDER[:36]`)
- Exit-sync: mandatory reduce-only live close on every TP/SL/TIMEOUT +
  mandatory Telegram receipt; boot reconcile + 60-cycle periodic orphan sweep
- `FLATTEN_ON_SHUTDOWN=true` — every stop/restart closes all live legs

## Model artifact
- `models/meta_labeler.joblib` md5: `65e8aed287d74eab5f1f26f1f5b4f99f`
- Trained 2026-09-12 on 854,324 K60 labels (48 assets), OOF AUC 0.572
- Threshold 0.61 (user decision 2026-09-12): 33-asset sweep +0.156%/trade
  in-sample (N=83k); thin live flow (~p99.9+)
- Pinned copies: `models/backup_33asset_20260912/` (33-asset baseline),
  `models/backup_k30/` (original K30 baseline), `models/backup_k10/`

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
6. MAX_OPEN_POSITIONS=3 cap (prevents over-leverage on 48-asset universe)
7. Orderbook history cap 25 (latency: /status <0.4s vs ~5s)
8. tg-bot `state_prices()` fast path (last close from in-state price_history,
   avoids ~1.3s testnet round-trip on /status critical path)
9. `conftest.py` TESTNET_LIVE=False global mock (tests never touch exchange)

## Restore path (fresh machine)
1. Clone repo, checkout tag `alpha3-live-baseline-2026-09-12`
2. Write `.env` with live keys + `BINANCE_USE_LIVE=true`,
   `TRADING_MODE=live`, `BINANCE_USE_TESTNET=false` (never commit `.env`)
3. `systemctl --user enable --now alpha3-dry-runner alpha3-tg-bot`
4. Confirm boot log: `Meta-labeler: LOADED (threshold=0.61, features=36)`,
   `Binance: MAINNET`, then `META-PASS`/`META-FILTER` on entries and
   `LIVE CLOSE … flattened` on exits
5. Expect bootstrap parse errors on testnet-only symbols (UAIUSDT,
   ANTHROPICUSDT, ZESTUSDT, PONSUSDT) — non-blocking, symbol skipped

## Ledger note
Paper ledger (`dry_data/alpha3_state.json`) is session state, NOT part of
this baseline — resets start from CAP=$10; running equity is preserved
across restarts except flatten-on-shutdown closes.