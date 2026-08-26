"""Shared constants for the Alpha 3 meta-labeler pipeline.

All parameters match alpha3_dry_runner.py exactly — the meta-labeler
must label what the runner actually trades.
"""

K = 10            # momentum lookback (bars)
H = 100            # hold horizon (bars)
WARMUP = H + 10   # bars before first entry allowed
TP_PCT = 0.035     # +3.5% take-profit
SL_PCT = -0.035    # -3.5% stop-loss (as fraction of entry, negative)
FEE_RATE = 0.0002  # 0.02% taker fee per side
INTERVAL_SEC = 60  # 1-minute bars
HOLDINGS = ['HANAUSDT', 'STRKUSDT', 'ONGUSDT', 'BMTUSDT', 'STXUSDT', 'PROMUSDT', 'PLAYUSDT']

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
