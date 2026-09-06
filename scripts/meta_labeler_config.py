"""Shared constants for the Alpha 3 meta-labeler pipeline.

All parameters match alpha3_dry_runner.py exactly — the meta-labeler
must label what the runner actually trades.

K note (2026-09-06): the alpha3 runner moved to momentum K=40 on 2026-09-06
 ('alpha3learn'); K here now reflects the live runner. The canonical model
 artifact (models/meta_labeler.joblib) stores config.K=40, the same retrain date.
 Verified feature set is K-independent; the retrain is required because the
 label/signal set (momentum direction) changes with K.
"""

K = 40            # momentum lookback (bars, alpha3 live runner)
H = 75             # hold horizon (bars)
WARMUP = H + 10   # bars before first entry allowed
TP_PCT = 0.025     # +2.5% take-profit
SL_PCT = -0.02     # -2% stop-loss (matches runner LOSS_PCT / sl_price = entry*0.98)
FEE_RATE = 0.0005  # 0.05% taker fee per side (feeTier 0 LIVE USDⓈ-M)
INTERVAL_SEC = 60  # 1-minute bars
HOLDINGS = ['TRIAUSDT', 'QUSDT', 'MAGMAUSDT', 'TRADOORUSDT', 'APRUSDT', 'UAIUSDT', 'DOODUSDT', 'BULLAUSDT', 'JCTUSDT']  # "pump" group (BTR removed, 4 new: UAI/DOOD/BULLA/JCT, 2026-09-06)

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
    'n_jobs': -1,  # perf-only: parallel trees do not change the fitted model
}
PROB_THRESHOLD_DEFAULT = 0.50  # meta-label: enter if P(win) > threshold (restored to 0.50 for K=40 retrain, 2026-09-06)

# Additional constants for Telegram bot compatibility
LEVERAGE = 20
STAKE_PCT = 0.20
WIN_PCT = 0.025   # +2.5% take-profit
LOSS_PCT = -0.02  # -2% stop-loss
