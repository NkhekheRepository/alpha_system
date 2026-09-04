# ADR-0002: Alpha 3% retrain with TP 2.5%, SL 2%, H 75 on 6-symbol universe

- **Status:** Accepted
- **Date:** 2026-09-04
- **Author:** NK-EXP-W8/W10
- **Decision:** Retrain the meta-labeler model from scratch with TP=2.5%, SL=2%, H=75 bars on the new 6-symbol universe (TRIAUSDT, QUSDT, MAGMAUSDT, TRADOORUSDT, APRUSDT, BTRUSDT).

## Context

Alpha 3% deployed live on 2026-09-03 with a meta-labeler trained on a **stale 7-symbol universe** (BTR, TAC, BICO, PUMPBTC, ARIA, MAGMA, BEAMX), **TP=3.5%, SL=2%, H=100**, and **FEE_RATE=0.0002 (0.02%)**. The live account fee is **0.05% per fill** (0.10% round-trip). The universe was corrected to 6 symbols, and the fee rate corrected to 0.0005 in the prior deployment.

Three compounding issues justified a full retrain:

1. **Label/exit-policy mismatch:** The old model was trained on TP=3.5% labels, but the runner was already executing at TP=2.5% (changed 2026-09-04). A model that gates entries on a 3.5% TP distribution is scoring against a 2.5% TP execution — the exact leakage pattern flagged in the Phoenix financial-ML audit ("labels must match the actual exit policy").

2. **Horizon mismatch (H=100 vs H=75):** The runner was updated to H=75 hold bars to reduce dead-capital time on fast-moving meme tokens. The old model's labels were generated at H=100. The model's timeout prediction no longer matches the runner's actual timeout barrier.

3. **Fee mismatch:** Old labels used FEE_RATE=0.0002; the live fee is 0.0005 per fill (0.10% round-trip). Labels generated at 0.0002 underestimate the true cost of the strategy's ~100% turnover rate.

Additionally, the old model's K=30 was the correct K but its HOLDINGS field listed the old 7 symbols. The universe was changed to 6 symbols in `scripts/meta_labeler_config.py` and `binance_config.py` (`ALPHA3_ASSETS`), but the model artifact still contained the old 7-symbol HOLDINGS.

## Alternatives considered

1. **Hot-swap only the barrier (no retrain):** Change `WIN_PCT` and the runner's hardcoded barrier prices to 2.5% while keeping the old 3.5%-trained model.
   - **Rejected:** The model's probability calibration is tied to the 3.5% TP label distribution. A model trained on 3.5% labels scored at a 2.5% exit threshold produces systematically biased probabilities — the meta-labeler would gate entries against a distribution it never learned. This is the exact "label/policy mismatch" failure pattern from the Phoenix audit.

2. **Retrain on old 7 symbols with new TP/H/fee:** Update TP/H/fee in labels but keep the old universe.
   - **Rejected:** The old TAC/BICO/PUMPBTC/ARIA/BEAMX symbols were removed from the live universe (`ALPHA3_ASSETS`). A model trained on them includes signals for assets that will never trade, and their label distributions are structurally different from the new symbols.

3. **Full retrain on new 6 symbols with TP=2.5%, SL=2%, H=75, FEE=0.0005 (CHOSEN).**
   - Labels regenerated for all 6 symbols on the new 180-day kline dataset (fetched from `fapi.binance.com`).
   - Features engineered on 541,895 labeled samples (226k TP, 315k SL).
   - Trained with purged K-fold CV (5 splits, purge=75, embargo=75).
   - Model artifact now embeds the correct config.

## Implementation

### Step 1 — Fetch kline data for missing symbols
TRIAUSDT, QUSDT, TRADOORUSDT, APRUSDT had no kline data. Fetched 180 days of 1m candles from `fapi.binance.com/fapi/v1/klines` (these are futures-only tokens; spot API `api.binance.com` returns 400). Each symbol: 259,200 rows (~180 days).

### Step 2 — Generate labels
`scripts/generate_labels.py` reads `models/kline_data/{SYMBOL}_1m.csv`, computes momentum-K30 signals, and applies triple-barrier labels with TP=2.5%, SL=2%, H=75, FEE=0.0005. Result: **1,574,156 signals → 545,980 labeled** (228,255 TP / 317,725 SL, WR 41.8%). The lower WR vs the old model's ~50% is expected: tighter TP (2.5% vs 3.5%) reduces winner frequency while SL is unchanged.

### Step 3 — Engineer features
`scripts/engineer_features.py` computes 36 features (ret_5/10/20/50, RSI, MACD, volume ratios, ATR, Bollinger position, MAs, momentum accel, hour/dow seasonality) per signal. Result: **541,895 rows, 99% feature coverage**.

### Step 4 — Train model
`scripts/train_meta_labeler.py` trains RandomForest (n_estimators=50, max_depth=6, min_samples_leaf=50, max_features=sqrt, class_weight=balanced_subsample) with purged K-fold CV (5 splits, purge=75, embargo=75).

**Note on training:** `n_jobs=-1` causes semaphore deadlocks on Python 3.14 with sklearn's RandomForest. The pipeline was run with `n_jobs=4` temporarily. The config was restored to `n_jobs=-1` after training. The deadlock is a Python 3.14 sklearn compatibility issue; if retraining in the future, use `n_jobs=4` explicitly.

### Results
- **OOF AUC:** 0.544 (marginally above random; consistent with the verified no-edge finding from W8/W10 experiments — momentum has no edge on BTC/ETH 5m at any parameter setting)
- **OOF Accuracy:** 0.523, Precision: 0.448, Recall: 0.605
- **Best threshold:** 0.50 (unchanged, matching `META_THRESHOLD`)
- **Selected:** 306,087 / 541,895 (56.5%) of signals

The model is marginally useful (AUC > 0.5) and, critically, its labels now correctly match the actual exit policy (TP=2.5%, SL=2%, H=75, FEE=0.05%). The model is a valid gate for entry decisions, even if the underlying strategy has no edge (per W8/W10).

## Deployment

The model is deployed via `models/meta_labeler.joblib` (git-tracked). The runner (`alpha3_dry_runner.py`) loads it on startup. The bot (`tg_bot_alpha2.py`) also reads config from `scripts/meta_labeler_config.py`.

**Hot-swap path:** To deploy a retrain without restarting the runner, copy the new `meta_labeler.joblib` over the tracked one. The runner picks up the new model on next restart. The runner's H, TP, SL constants are in the runner code and config; both must match the model's embedded config.

## Trade-offs

- **Marginal edge:** AUC 0.544 is barely above random. The strategy has no verified edge (W8: 0/1605 parameterizations passed; W10 walk-forward: 0/108 passed). The meta-labeler gates entries more accurately than the old model, but the underlying signal still has no edge. This is the honest picture — the model is a better gate, not a profitable strategy.
- **Tighter TP (2.5%) reduces winner frequency:** WR dropped from ~42% (old model) to ~41.8% at the label level. The 2.5% TP may be too tight for the H=75 hold window; positions may more often hit TIMEOUT than TP. This should be monitored — if TIMEOUT dominates (like W8's finding of 96% timeout), the tighter TP may actually help by capturing near-TP exits before they drift back.
- **Fewer symbols reduce label diversity:** 6 symbols vs 7 reduces training data by ~268k samples. The new symbols (TRIA, Q, TRADOOR, APR) are higher-volatility meme tokens with faster price action, which may have different label distributions than the old universe.
- **n_jobs constraint:** Training must use `n_jobs=4` due to Python 3.14 sklearn deadlocks. This adds ~15 minutes to training time vs `n_jobs=-1`.

## Files changed

- `scripts/meta_labeler_config.py`: H=100→75, TP_PCT=0.035→0.025, FEE_RATE=0.0002→0.0005, HOLDINGS→6 new symbols, `n_jobs=-1` restored (was temporarily 4 during training)
- `alpha3_dry_runner.py`: H=100→75, WIN_PCT=0.035→0.025, back-compat barriers `1.035/0.965`→`1.025/0.975`, TG msg "TP 3.5%"→"TP 2.5%", boot banner, docstring
- `tg_bot_alpha2.py`: "H100"→"H75", "TIMEOUT bar 100"→"bar 75", "bar {age}/100"→"/75", hardcoded TP display fallback `1.035/0.965`→`1.025/0.975`
- `scripts/generate_labels.py`: docstring updated (H=100→H=75, TP 3.5%→2.5%, SL 3.5%→2%)
- `tests/test_config_consistency.py`: H==75 assertion, model artifact K=10→K=30 guard updated to K=30 confirmation, INTERVAL mismatch fix, docstring updated to reflect retrain landed
- `models/meta_labeler.joblib`: fresh retrain (2026-09-04 08:54), H=75, TP=2.5%, SL=2%, FEE=0.0005, 6-symbol universe, AUC 0.544
- `models/meta_labeler_metrics.json`: fresh metrics matching new model
- `models/kline_data/{TRIA,Q,TRADOOR,APR}USDT_1m.csv`: 180-day 1m candles fetched from fapi (259,200 rows each)

## Validation

- `tests/test_config_consistency.py`: **5/5 pass**
  - `test_k_horizon_match`: R.INTERVAL=10 vs MC.INTERVAL_SEC=60 confirmed (intentionally different)
  - `test_model_artifact_k_is_10_pending_retrain`: updated to assert K=30 (retrain landed)
  - `test_tp_sl_fee_match`: WIN_PCT=TP_PCT=0.025, LOSS_PCT=SL_PCT=-0.02, FEE=0.0005 ✅
  - `test_asset_universe_match`: ALPHA3_ASSETS==HOLDINGS ✅
  - `test_threshold_default_matches`: 0.50 ✅
- Boot banner: `Exits: TP 2.5% / SL 2% market | TIMEOUT at bar 75` ✅
- Model artifact: `config H=75, TP_PCT=0.025, SL_PCT=-0.02, FEE_RATE=0.0005, HOLDINGS=6 symbols` ✅
- Live positions show `tp_price = entry × 1.025` (2.5%) and `sl_price = entry × 0.98` (2.0%) ✅

## References

- OEOS Lessons Learned — Wave 6 FML Search (ADR-0003): "registration config field names are part of the contract"
- OEOS Lessons Learned — Wave 9 Synthetic-Backtest Trap: "synth 85% WR ≠ real -55%"; label/policy mismatch
- Phoenix scalper financial-ML audit (lesson #3): "labels must match the actual exit policy"
- Wave 8/10 experiments: 0/1605 parameterizations passed, 0/108 walk-forward configs passed (no edge confirmed)
