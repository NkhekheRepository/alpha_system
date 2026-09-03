"""Shared constants for the Alpha 3 meta-labeler pipeline.

All parameters match alpha3_dry_runner.py exactly — the meta-labeler
must label what the runner actually trades.

K note (2026-08-31): the alpha3 runner deliberately moved to momentum K=30 on
2026-08-30 ('alpha3learn'); K here now reflects the live runner. The canonical
model artifact (models/meta_labeler.joblib) still stores config.K=10 and alpha4
still trains/enters at K=10 — a retrain to K=30 is pending. Until that retrain
happens, the alpha3 meta-labeler filter gates K30 entries with a K10-trained
model (documented divergence; verified feature set is K-independent).
"""

K = 30            # momentum lookback (bars, alpha3 live runner)
H = 100            # hold horizon (bars)
WARMUP = H + 10   # bars before first entry allowed
TP_PCT = 0.035     # +3.5% take-profit
SL_PCT = -0.02     # -2% stop-loss (matches runner LOSS_PCT / sl_price = entry*0.98)
FEE_RATE = 0.0002  # 0.02% taker fee per side
INTERVAL_SEC = 60  # 1-minute bars
HOLDINGS = ['BTRUSDT', 'TACUSDT', 'BICOUSDT', 'PUMPBTCUSDT', 'ARIAUSDT', 'MAGMAUSDT', 'BEAMXUSDT']  # "pump" group

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
PROB_THRESHOLD_DEFAULT = 0.50  # meta-label: enter if P(win) > threshold

# Additional constants for Telegram bot compatibility
LEVERAGE = 20
STAKE_PCT = 0.20
WIN_PCT = 0.035   # +3.5% take-profit
LOSS_PCT = -0.02  # -2% stop-loss
