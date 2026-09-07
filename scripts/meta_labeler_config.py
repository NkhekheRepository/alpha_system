"""Shared constants for the Alpha 3 meta-labeler pipeline.

All parameters match alpha3_dry_runner.py exactly — the meta-labeler
must label what the runner actually trades.

K note (2026-09-07): alpha3 moved K=40 -> K=60, H=75 -> H=100, TP 2.5% -> 3%,
 SL 2% -> 1.5% (user deploy; barrier stats H100 WR26.7% K60 best).
 K here now reflects the live runner. The canonical model artifact
 (models/meta_labeler.joblib) stores config.K=60, same retrain date.
 Verified feature set is K-independent; the retrain is required because the
 label/signal set (momentum direction) changes with K.
"""

K = 60            # momentum lookback (bars, alpha3 live runner)
H = 100            # hold horizon (bars)
WARMUP = H + 10   # bars before first entry allowed (=110)
TP_PCT = 0.03      # +3% take-profit
SL_PCT = -0.015    # -1.5% stop-loss (matches runner LOSS_PCT / sl_price = entry*0.985)
FEE_RATE = 0.0005  # 0.05% taker fee per side (feeTier 0 LIVE USDⓈ-M)
INTERVAL_SEC = 60  # 1-minute bars
HOLDINGS = ['TRIAUSDT', 'QUSDT', 'MAGMAUSDT', 'TRADOORUSDT', 'APRUSDT', 'UAIUSDT', 'DOODUSDT', 'BULLAUSDT', 'JCTUSDT', 'ZECUSDT']  # "pump" group + ZEC (2026-09-07)

# Training parameters
PURGE_BARS = H        # purge gap between train/test (≥ label horizon)
EMBARGO_BARS = H      # embargo after test set to prevent leakage
N_SPLITS = 5          # purged K-fold splits
MIN_TRADES_PER_FOLD = 20  # minimum trades for a valid fold
RF_PARAMS = {
    'n_estimators': 50,
    'max_depth': 6,
    'min_samples_leaf': 50,
    'max_features': 'sqrt',
    'class_weight': 'balanced_subsample',
    'random_state': 42,
    'n_jobs': 2,  # 3GB box swaps to death at -1/4 (2026-09-07); same fitted model, fewer workers
}
PROB_THRESHOLD_DEFAULT = 0.57  # meta-label: enter if P(win) > threshold (in-sample prec 0.362 sel 10.6%; user override 2026-09-07)

# Additional constants for Telegram bot compatibility
LEVERAGE = 20
STAKE_PCT = 0.20
WIN_PCT = 0.03    # +3% take-profit
LOSS_PCT = -0.015 # -1.5% stop-loss
