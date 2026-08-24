# ALPHA SYSTEM — CONFIGURATION VERSIONS

Formal version record for Alpha 3% dry-runner configurations. Each version is
tagged in git (`a3-vX.Y-name`) with the exact parameter set below.

---

## v3.1 — `a3-v3.1-zec` (current)

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
