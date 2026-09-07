# ADR 0003: K/H Grid Search for TP 3% / SL 1.5% (OOS)

Date: 2026-09-07
Status: Pre-registered — execution pending
Deciders: user (NK) + opencode
Context: TP3/SL1.5 requested; current model TP2.5/SL2 K40 H75 cannot be hot-swapped (labels must match exit policy, AGENTS.md L2).

## Decision

Search 12 configs: K × H at fixed TP 3% SL 1.5%.

- K: [20, 30, 40, 60] (bars, momentum `closes[i] > closes[i-K]`)
- H: [50, 75, 100] (bars, triple-barrier vertical horizon)
- TP_PCT=0.03 SL_PCT=-0.015 FEE_RATE=0.0005 HOLDINGS 9 (TRIA/Q/MAGMA/TRADOOR/APR/UAI/DOOD/BULLA/JCT) — per binance_config.py:58
- Grid = 12 = 4×3, DSR penalty controlled (L8 DSR 0.995→0.86@10).

## Pipeline per config (out-of-box only)

1. `scripts/generate_labels.py:compute_labels_vectorized(k=K,h=H,tp=0.03,sl=-0.015)` → `labeled_signals.csv` (in-memory temp, not overwriting canonical)
2. `scripts/engineer_features.py:compute_features_at_indices` at labeled `time_idx` → `labeled_features` (36 feats, purge NaN)
3. `scripts/train_meta_labeler.py:purged_kfold_indices(n, purge=H, embargo=H)` N_SPLITS=5 RF 50t depth6 min50 → OOF probs/labels
4. Metrics per config: G1 `≥20 trades/fold` on test folds, G2 `net + on ≥2/3 train folds`, then `median return, median DD, Sharpe, ruin` on OOS bootstrap (3000×100, NOTIONAL 0.20×20=4.0, START 10). Best = max `median*(1-ruin)-median_dd*0.5`.

No in-sample MC ranking; selection is OOS gate.

## Consequences

- On pass: retrain canonical model with winning K/H, update `scripts/meta_labeler_config.py:13-14`, `alpha3_dry_runner.py:340-341`, `models/meta_labeler.joblib:config`, guarded by `tests/test_config_consistency.py:21`.
- On 0/12 pass: null result, keep K40 H75.

## Alternatives Considered

- Hot-swap TP3/SL1.5 on K40 H75 gate without retrain — rejected (AGENTS.md L2).
- In-sample TP/SL repricing `scripts/mc_tp_sl_sweep.py` — informative not OOS (already run, TP5/SL1.5 best #1, TP3/SL1.5 rank 4).
- Wider H grid [30] — deferred to keep N=12.
