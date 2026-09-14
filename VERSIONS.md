# ALPHA SYSTEM — CONFIGURATION VERSIONS

Formal version record for Alpha 3% dry-runner configurations. Each version is
tagged in git (`a3-vX.Y-name`) with the exact parameter set below.

---

## v5.1 — `a3-v5.1-halfkelly` (current)

**Identity**: A2 half-Kelly position sizing. Stake 20% → 12% (leverage stays 20x): notional 4.0x → 2.4x equity per trade.

**Evidence** (2026-09-14, 36-trade replay + Kelly + 100-trade bootstrap): full Kelly = 4.64x notional (current 4.0x was near-full-Kelly — optimal for log-growth only if the distribution were known; with n=36 it is reckless). Half-Kelly = 2.32x. At 2.4x: 36-trade replay final $11.11 (+11.1%) vs $11.39 (+13.9%) at 4.0x, while realized maxDD drops 43.7% → 28.5% and 100-trade P(DD>50%) drops 50% → ~10% at unchanged ~74% P(profit). Per-trade equity impact at $11: SL −$0.42 (−3.8%) / TP +$0.77 (+7.0%), was −$0.70/+$1.28.

| Parameter | Value |
|-----------|-------|
| Base capital | $10 USDT (synthetic) |
| Margin/trade | **12%** of equity, compounding |
| Leverage | 20x |
| Notional/trade | ~$27/trade (12% × 20x × $11.28, compounding) |

Ledger: **continued** — stake migration preserves all 36 trades + $11.28 equity (verified `stake 0.2->0.12` migrate log, no reset). Live legs (demo + testnet) mirror 12% via `STAKE_PCT`/`STAKE_PCT_TESTNET`.

**Deploy note:** the installed unit `~/.config/systemd/user/alpha3-dry-runner.service` is a *copy* of the repo file — editing `systemd/` alone does not redeploy. Must `cp` + `daemon-reload` + `restart` (per `deploy.sh`).

---

## v5.0 — `a3-v5.0-48asset` (previous)

**Identity**: 48-asset universe expansion + latency optimization + model retrained on 48 assets.

| Parameter | Value |
|-----------|-------|
| Base capital | $10 USDT (synthetic) |
| Margin/trade | **20%** of equity, compounding |
| Leverage | 20x |
| Notional/trade | ~$40/trade (20% × 20x × $10, compounding) |
| Universe | **48 assets** (TRIAUSDT, QUSDT, MAGMAUSDT, TRADOORUSDT, APRUSDT, UAIUSDT, DOODUSDT, BULLAUSDT, JCTUSDT, ZECUSDT, RAYSOLUSDT, XRPUSDT, BTCUSDT, ETHUSDT, SOLUSDT, KOMAUSDT, VTHOUSDT, IOSTUSDT, BEATUSDT, OPENAIUSDT, SNXUSDT, SUIUSDT, XLMUSDT, PUMPUSDT, 1000PEPEUSDT, BMTUSDT, EIGENUSDT, HEIUSDT, LINKUSDT, RENDERUSDT, ROSEUSDT, XVGUSDT, ANTHROPICUSDT, HYPEUSDT, CRVUSDT, DASHUSDT, ARBUSDT, INJUSDT, DOGEUSDT, UNIUSDT, JUPUSDT, XMRUSDT, TAOUSDT, REZUSDT, FLOCKUSDT, ZESTUSDT, PONSUSDT, MARSCOINUSDT) |
| Primary signal | momentum-K60 (`ph[-1] > ph[-61]` → long) per asset |
| **Meta-labeler** | RF secondary classifier → P(win); enter only if P ≥ **0.61** |
| Meta features | 36 at signal bar (momentum/vol/RSI/rollback/etc.) via `meta_features.py` |
| Warmup | 110 polls (H+10) per symbol |
| Hold horizon | H = 100 bars (100 min @ 10s polls) |
| Exit — upper | TP +3%, market barrier, every poll |
| Exit — lower | SL −1.5%, market barrier, every poll |
| Exit — vertical | TIMEOUT at bar 100, last MARKET price |
| Max open positions | **3** (cap concurrent positions; 20% × 20x each) |
| Circuit breaker | 3 consecutive losses → 50-bar cooldown |
| Orderbook cap | **25** snapshots/symbol (latency optimization; was 200) |
| Model | `models/meta_labeler.joblib` sha `1091b967`, OOF AUC 0.572, 854k samples (48 assets) |
| Threshold | **0.61** (user decision 2026-09-12; 33-asset sweep +0.156%/trade in-sample) |

Ledger: **continued** from v4.0 — existing equity preserved across restarts. No reset.
Bootstrap failures on testnet: UAIUSDT, ANTHROPICUSDT, ZESTUSDT, PONSUSDT (parse error `'o'` — non-blocking, symbol skipped).

---

## v4.0 — `a3-v4.0-metalabeler` (previous)

**Identity**: v3.1 engine + **meta-labeler secondary filter** + 7.5% margin + demo-fapi live hedge + effective-equity tracking.

| Parameter | Value |
|-----------|-------|
| Base capital | $100 USDT (synthetic) |
| Margin/trade | **7.5%** of equity, compounding |
| Leverage | 50x |
| Notional/trade | **$375** (cap × stake × lev, per asset) |
| Universe | BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ZECUSDT (6 assets, 60s polls) |
| Primary signal | momentum-K10 (`ph[-1] > ph[-11]` → long else short) per asset |
| **Meta-labeler** | RF secondary classifier → P(win); enter only if P ≥ **0.50** |
| Meta features | 36 at signal bar (momentum/vol/RSI/rollback/etc.) via `meta_features.py` |
| Warmup | 200 polls (bootstrap OHLCV history) per symbol |
| Hold horizon | H = 75 bars (75 min @ 60s polls) |
| Exit — upper | TP +2%, market barrier, every poll |
| Exit — lower | SL −2%, market barrier, every poll |
| Exit — vertical | TIMEOUT at bar 75, last MARKET price |
| Demo entry | **MARKET** order (mirrors paper fill; was LIMIT — unfilled bug) |
| Demo exit | **MARKET** order + bracket TP/SL algo orders |
| Demo leverage | set to 50x at startup via `set_leverage_all` (Binance default 20x) |
| Circuit breaker | 3 consecutive losses → 50-bar cooldown |
| Equity tracking | `equity` (realized) + `effective_equity` (capital + unrealized), like Alpha 1 |
| Model | `models/meta_labeler.joblib` (frozen, OOF AUC 0.625, OOS +8.9pp synthetic) |

Ledger: reset at deploy (fresh $100 start). Meta-labeler trained on Alpha 3
synthetic-resolution distribution (iid p=0.85) — machinery validated, live edge UNKNOWN.

---

## v3.1 — `a3-v3.1-zec`

**Identity**: v3.0 + ZEC — same engine, 6-asset universe.

| Parameter | Value |
|-----------|-------|
| Base capital | $100 USDT (synthetic) |
| Margin/trade | 3% of equity, compounding |
| Leverage | 50x |
| Notional/trade | $150 (cap × stake × lev, per asset) |
| Universe | BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, **ZECUSDT** (6 assets, 60s polls) |
| Signal | momentum-K10 (`ph[-1] > ph[-11]` → long else short) per asset |
| Warmup | 85 polls (H+10) per symbol |
| Hold horizon | H = 75 bars (75 min @ 60s polls) |
| Exit — upper | TP +2%, market barrier, every poll |
| Exit — lower | SL −2%, market barrier, every poll |
| Exit — vertical | TIMEOUT at bar 75, last MARKET price |
| Flip/RNG | none |
| Circuit breaker | 3 consecutive losses → 50-bar cooldown (immediate-fire + entry guard) |
| Min notional (demo) | BTC 50, ETH 20, SOL/BNB/XRP/ZEC 5 — all satisfied by $150 (ZEC step 0.001, qty ~0.179 @ $832) |
| Bot | `tg_bot_alpha2.py` `get_prices()` reads `ALPHA3_ASSETS` (now 6) |
| Banner | `Assets: BTC + ETH + SOL + BNB + XRP + ZEC (6 assets)` dynamic |

Ledger: **additive** from v3.0 — existing 5-asset ledger preserved; ZEC warms up from 0 polls (85 before first entry). No reset.

---

## v3.0 — `a3-v3.0-multiasset`

**Identity**: Alpha 1/2 triple-barrier engine expanded to 5-asset universe. Same market barriers, same stake.

| Parameter | Value |
|-----------|-------|
| Base capital | $100 USDT (synthetic) |
| Margin/trade | 3% of equity, compounding |
| Leverage | 50x |
| Notional/trade | $150 (cap × stake × lev, per asset) |
| Universe | BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT (5 assets, 60s polls) |
| Signal | momentum-K10 (`ph[-1] > ph[-11]` → long else short) per asset |
| Warmup | 85 polls (H+10) per symbol |
| Hold horizon | H = 75 bars (75 min @ 60s polls) |
| Exit — upper | TP +2%, market barrier, every poll |
| Exit — lower | SL −2%, market barrier, every poll |
| Exit — vertical | TIMEOUT at bar 75, last MARKET price |
| Flip/RNG | none |
| Circuit breaker | 3 consecutive losses → 50-bar cooldown (immediate-fire + entry guard) |
| Min notional (demo) | BTC 50, ETH 20, SOL/BNB/XRP 5 — all satisfied by $150 |
| Bot | `tg_bot_alpha2.py` `get_prices()` now covers all 5 for /live unrealized PnL |

Ledger: **additive** from v2.0 — existing BTC/ETH positions preserved; SOL/BNB/XRP warm up from empty (85 polls before first entry). No reset.

---

## v2.0 — `a3-v2.0-flip`

**Identity**: Pure synthetic flip resolution (W9 bugged-profile revert). No market barriers.

| Parameter | Value |
|-----------|-------|
| Base capital | $100 USDT (synthetic) |
| Margin/trade | 1% of equity ($1.00), compounding |
| Leverage | 48x |
| Notional/trade | $48.00 |
| Signal | momentum-K10 (`ph[-1] > ph[-11]` → long else short) |
| Warmup | 15 polls (K+5) |
| Hold horizon | H = 15 bars (15 min @ 60s polls) |
| Exit — every trade | Coin flip `p=0.85` → +2% / −2%; exit price mirrored for shorts; no TP/SL/TIMEOUT |
| Flip/RNG | numpy default_rng(seed=1), deterministic per seed |
| Circuit breaker | 3 consecutive losses → 50-bar cooldown (hardened: immediate-fire + entry guard) |
| Expected returns | +0.672%/trade by construction (~+29%/day at 38 trades/day; MC median 30d ≈ +$67.8k) |

Ledger: CONTINUOUS from v1.0 era (no reset — carried positions flip-resolved on first cycle).
Prior TB snapshot preserved at `a3-v1.0-triple-barrier` tag + `alpha3_*.v10-tb.bak`.

---

## v1.0 — `a3-v1.0-triple-barrier` (commit c8c983a lineage)

**Identity**: Alpha 1/2 engine clone at leveraged stake. No synthetic elements.

| Parameter | Value |
|-----------|-------|
| Base capital | $100 USDT (synthetic) |
| Margin/trade | 1% of equity ($1.00), compounding |
| Leverage | 48x |
| Notional/trade | $48.00 |
| Signal | momentum-K10 (`ph[-1] > ph[-11]` → long else short) |
| Warmup | 85 polls (H+10) |
| Hold horizon | H = 75 bars (75 min @ 60s polls) |
| Exit — upper | TP +2%, market barrier, evaluated every poll |
| Exit — lower | SL −2%, market barrier, evaluated every poll |
| Exit — vertical | TIMEOUT at bar 75, exits at last MARKET price |
| Flip/RNG | none |
| Circuit breaker | 3 consecutive losses → 50-bar cooldown (immediate-fire + entry guard, harness-tested 13/13) |
| Expected returns | market-driven ≈ 0 to negative (matches A2 backtest profile) |

Ledger era: `alpha3_*.v10.bak` archives.

---

## Historical (pre-version-control) eras — ledger `.bak` archive index

| Era | Ledger backup | Exit method | Staking |
|-----|---------------|-------------|---------|
| synthetic-v1 | `*.synthetic-v1.bak` | pure flip H=15, W9 formula f×100k×pct | fixed notional f∈{0.03,1,8.75,35,10} |
| v2 | `*.v2-30pct.bak` | flip H=15 | 30% of equity flat ($30) |
| v3–v5 | `*.v3/v4/v5.bak` | flip H=15 | $100 base experiments ($30/$12/$1) |
| v6 | `*.v6.bak` | flip H=15 | $0.75 × 48x |
| v7 | `*.v7.bak` | hybrid: TP/SL market + flip fallback H=15 | $0.75 × 48x |
| v8 | `*.v8.bak` | hybrid (short-sign fix) | $1 × 48x |
| v9 | `*.v9.bak` | triple-barrier H=15→75 transition | $1 × 48x |

---
