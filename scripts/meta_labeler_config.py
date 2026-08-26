"""Shared constants for the Alpha 3 meta-labeler pipeline.

All parameters match alpha3_dry_runner.py exactly — the meta-labeler
must label what the runner actually trades.
"""

K = 60            # momentum lookback (bars) — 60*10s = 600s (was 10*60s)
H = 100            # hold horizon (bars) — 100*10s = 1000s (was 600*10s = 6000s)
WARMUP = 60        # keep low for immediate trading
TP_PCT = 0.035     # +3.5% take-profit
SL_PCT = -0.02     # -2% stop-loss (as fraction of entry, negative)
WIN_PCT = 0.035    # +3.5% win threshold (for compatibility with runner)
LOSS_PCT = -0.02   # -2% loss threshold (for compatibility with runner)
FEE_RATE = 0.0002  # 0.02% taker fee per side
INTERVAL_SEC = 10  # 10s bars — 6x more responsive (was 60s)
HOLDINGS = ['HANAUSDT', 'STRKUSDT', 'ONGUSDT', 'BMTUSDT', 'STXUSDT', 'PROMUSDT', 'PLAYUSDT']
LEVERAGE = 20.0     # leverage multiplier
STAKE_PCT = 0.20    # stake percentage (20% of capital) — synced to runner
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
