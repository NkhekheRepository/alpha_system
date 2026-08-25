#!/usr/bin/env python3
"""Test primary (momentum signal) + secondary (meta-labeler) HARMONY with
Purged K-Fold Cross-Validation (Lopez de Prado). Non-destructive: does NOT
overwrite models/meta_labeler.joblib. Verifies (A) the live runner feeds the
model the exact features it was trained on, and (B) the secondary model
improves the primary leakage-free (cross-validated).
"""
import sys, json, joblib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import alpha3_dry_runner as R
from meta_labeler_config import (
    PURGE_BARS, EMBARGO_BARS, N_SPLITS, MIN_TRADES_PER_FOLD, RF_PARAMS, PROB_THRESHOLD_DEFAULT
)
from train_meta_labeler import purged_kfold_indices
from scripts.meta_features import compute_features_at_index as train_feat

MODEL_FILE = ROOT / 'models' / 'meta_labeler.joblib'
FEATURE_FILE = ROOT / 'models' / 'labeled_features.csv'

print("=" * 70)
print("A. FEATURE-SCHEMA HARMONY  (live runner vs training)")
print("=" * 70)
md = joblib.load(MODEL_FILE)
model_feats = md['features']
runner_feats = list(R.FEATURE_ORDER)
print(f"  model features : {len(model_feats)}")
print(f"  runner features: {len(runner_feats)}")
schema_ok = set(model_feats) == set(runner_feats)
print(f"  schema match (set equality): {schema_ok}")
if not schema_ok:
    print("  missing in runner:", set(model_feats) - set(runner_feats))
    print("  extra  in runner:", set(runner_feats) - set(model_feats))

# numeric parity on synthetic data at idx=250 (both must agree)
rng = np.random.default_rng(0)
n = 400
closes = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
highs = closes + np.abs(rng.standard_normal(n) * 0.3)
lows = closes - np.abs(rng.standard_normal(n) * 0.3)
vols = 1000 + rng.standard_normal(n) * 100
r_f = R.compute_meta_features(closes, highs, lows, vols, 250)
t_f = train_feat(closes, highs, lows, vols, 250)
if r_f is None or t_f is None:
    print("  WARN: a function returned None at idx=250 (boundary)")
else:
    diffs = [abs(r_f[k] - t_f[k]) for k in model_feats if k in r_f and k in t_f]
    print(f"  numeric parity @idx=250: max|diff|={max(diffs):.3e}  mean|diff|={np.mean(diffs):.3e}")
    print(f"  => live runner reproduces training features EXACTLY"
          if max(diffs) < 1e-9 else "  => MISMATCH (broken harmony)")

print()
print("=" * 70)
print("B. CROSS-VALIDATED HARMONY  (Purged K-Fold, no leakage)")
print("=" * 70)
df = pd.read_csv(FEATURE_FILE)
exclude = ['time_idx', 'symbol', 'direction', 'entry_price', 'label', 'barrier_bar']
feat_cols = [c for c in df.columns if c not in exclude]
# Use the model's own feature list (authoritative training schema)
X = df[model_feats].values.astype(np.float32)
y = df['label'].values.astype(np.int32)
print(f"  samples={len(X):,}  features={X.shape[1]}  "
      f"purge={PURGE_BARS} embargo={EMBARGO_BARS} splits={N_SPLITS}")

folds = purged_kfold_indices(len(X))
all_p, all_l = [], []
for fi, (tr, te) in enumerate(folds):
    if len(te) < MIN_TRADES_PER_FOLD:
        print(f"  fold {fi+1}: SKIP (n={len(te)})"); continue
    rf = RandomForestClassifier(**RF_PARAMS)
    rf.fit(X[tr], y[tr])
    p = rf.predict_proba(X[te])[:, 1]
    all_p.extend(p); all_l.extend(y[te])
    sel = p >= PROB_THRESHOLD_DEFAULT
    pw = float(y[te].mean())
    fw = float(y[te][sel].mean()) if sel.sum() > 0 else float('nan')
    print(f"  fold {fi+1}: n={len(te):>6}  primary_WR={pw:.4f}  "
          f"filtered_WR={fw:.4f}  selected={sel.mean():.2%}")

all_p = np.array(all_p); all_l = np.array(all_l)
primary_wr = float(all_l.mean())
sel = all_p >= PROB_THRESHOLD_DEFAULT
filtered_wr = float(all_l[sel].mean()) if sel.sum() > 0 else float('nan')
auc = roc_auc_score(all_l, all_p)
acc = accuracy_score(all_l, (all_p >= 0.5).astype(int))
prec = precision_score(all_l, (all_p >= 0.5).astype(int), zero_division=0)
rec = recall_score(all_l, (all_p >= 0.5).astype(int), zero_division=0)

print()
print("  CROSS-VALIDATED (out-of-fold, leakage-free):")
print(f"    Primary-only WR : {primary_wr:.4f}  ({primary_wr*100:.2f}%)")
print(f"    Filtered WR     : {filtered_wr:.4f}  ({filtered_wr*100:.2f}%)")
print(f"    Improvement     : {(filtered_wr - primary_wr)*100:+.2f} pp")
print(f"    Selection rate  : {sel.mean():.2%}")
print(f"    AUC={auc:.3f}  Acc={acc:.3f}  Prec={prec:.3f}  Rec={rec:.3f}")

verdict = (schema_ok and (max(diffs) < 1e-9 if (r_f and t_f) else False)
           and filtered_wr > primary_wr and auc > 0.55)
print()
print("  HARMONY VERDICT:", "PASS" if verdict else "CHECK")

report = {
    "schema_match": schema_ok,
    "numeric_parity_max_diff": float(max(diffs)) if (r_f and t_f) else None,
    "cv_primary_wr": primary_wr,
    "cv_filtered_wr": filtered_wr,
    "cv_improvement_pp": (filtered_wr - primary_wr) * 100,
    "cv_selection_rate": float(sel.mean()),
    "cv_auc": float(auc), "cv_accuracy": float(acc),
    "cv_precision": float(prec), "cv_recall": float(rec),
    "verdict": "PASS" if verdict else "CHECK",
}
(ROOT / 'models' / 'harmony_cv_report.json').write_text(json.dumps(report, indent=2))
print("  report -> models/harmony_cv_report.json")
