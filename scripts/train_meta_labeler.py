#!/usr/bin/env python3
"""Train meta-labeler with purged cross-validation + embargo.

Uses RandomForest predict_proba directly (well-calibrated for RF).
Implements López de Prado's Purged K-Fold with embargo gap.
Outputs: models/meta_labeler.joblib (model + metadata)

Usage:
    python3 scripts/train_meta_labeler.py
"""

import sys, json, joblib
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler_config import (
    K, H, TP_PCT, SL_PCT, FEE_RATE, HOLDINGS,
    PURGE_BARS, EMBARGO_BARS, N_SPLITS, MIN_TRADES_PER_FOLD,
    RF_PARAMS, PROB_THRESHOLD_DEFAULT
)

FEATURE_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_features.csv'
MODEL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'meta_labeler.joblib'
METRICS_FILE = Path(__file__).resolve().parent.parent / 'models' / 'meta_labeler_metrics.json'


def purged_kfold_indices(n_samples, n_splits=N_SPLITS, purge=PURGE_BARS, embargo=EMBARGO_BARS):
    """Generate purged K-fold train/test indices with embargo."""
    indices = np.arange(n_samples)
    fold_size = n_samples // n_splits
    folds = []

    for i in range(n_splits):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < n_splits - 1 else n_samples
        test_idx = indices[test_start:test_end]

        purge_start = max(0, test_start - purge)
        purge_end = min(n_samples, test_end + purge + embargo)

        train_idx = np.concatenate([
            indices[:purge_start],
            indices[purge_end:]
        ])
        folds.append((train_idx, test_idx))

    return folds


def compute_metrics(y_true, y_pred, y_prob, prefix=""):
    """Compute classification metrics."""
    return {
        f"{prefix}auc": float(roc_auc_score(y_true, y_prob)),
        f"{prefix}accuracy": float(accuracy_score(y_true, y_pred)),
        f"{prefix}precision": float(precision_score(y_true, y_pred)),
        f"{prefix}recall": float(recall_score(y_true, y_pred)),
        f"{prefix}n_samples": int(len(y_true)),
        f"{prefix}n_positive": int(y_true.sum()),
        f"{prefix}n_negative": int((1 - y_true).sum()),
    }


def find_best_threshold(y_true, y_prob, thresholds=np.linspace(0.5, 0.9, 9)):
    """Find probability threshold that maximizes F1 score."""
    best_thresh = 0.5
    best_score = 0
    for thresh in thresholds:
        y_pred = (y_prob >= thresh).astype(int)
        if y_pred.sum() > 0:
            p = precision_score(y_true, y_pred, zero_division=0)
            r = recall_score(y_true, y_pred, zero_division=0)
            f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
            if f1 > best_score:
                best_score = f1
                best_thresh = thresh
    return best_thresh, best_score


def main():
    # Load features
    df = pd.read_csv(FEATURE_FILE)
    print(f"Loaded {len(df):,} samples from {FEATURE_FILE.name}")

    exclude = ['time_idx', 'symbol', 'direction', 'entry_price', 'label', 'barrier_bar']
    feat_cols = [c for c in df.columns if c not in exclude]
    print(f"Features: {len(feat_cols)}")

    X = df[feat_cols].values.astype(np.float32)
    y = df['label'].values.astype(np.int32)

    # Purged K-fold CV
    folds = purged_kfold_indices(len(X))
    print(f"Purged K-Fold: n_splits={N_SPLITS}, purge={PURGE_BARS}, embargo={EMBARGO_BARS}")

    all_train_probs = []
    all_train_labels = []
    all_test_probs = []
    all_test_labels = []
    fold_metrics = []

    for fold_idx, (train_idx, test_idx) in enumerate(folds):
        print(f"\n  Fold {fold_idx + 1}/{N_SPLITS}: train={len(train_idx):,}, test={len(test_idx):,}")

        if len(test_idx) < MIN_TRADES_PER_FOLD:
            print(f"    SKIP: test fold too small ({len(test_idx)} < {MIN_TRADES_PER_FOLD})")
            continue

        X_train, y_train = X[train_idx], y[train_idx]
        X_test, y_test = X[test_idx], y[test_idx]

        # Train RF (predict_proba is well-calibrated for RF)
        rf = RandomForestClassifier(**RF_PARAMS)
        rf.fit(X_train, y_train)

        # Predict probabilities directly
        train_prob = rf.predict_proba(X_train)[:, 1]
        test_prob = rf.predict_proba(X_test)[:, 1]

        # Find best threshold on train
        best_thresh, best_f1 = find_best_threshold(y_train, train_prob)
        print(f"    Best threshold: {best_thresh:.2f} (train F1: {best_f1:.3f})")

        # Evaluate on test at best threshold
        test_pred = (test_prob >= best_thresh).astype(int)
        metrics = compute_metrics(y_test, test_pred, test_prob, f"fold{fold_idx}_")
        metrics['best_threshold'] = best_thresh
        metrics['best_f1_train'] = best_f1
        fold_metrics.append(metrics)

        print(f"    Test AUC: {metrics['fold'+str(fold_idx)+'_auc']:.3f}, "
              f"Acc: {metrics['fold'+str(fold_idx)+'_accuracy']:.3f}, "
              f"Prec: {metrics['fold'+str(fold_idx)+'_precision']:.3f}, "
              f"Rec: {metrics['fold'+str(fold_idx)+'_recall']:.3f}")

        all_train_probs.extend(train_prob)
        all_train_labels.extend(y_train)
        all_test_probs.extend(test_prob)
        all_test_labels.extend(y_test)

    # Aggregate OOF (out-of-fold) metrics
    all_test_probs = np.array(all_test_probs)
    all_test_labels = np.array(all_test_labels)

    # Global threshold optimization on all OOF
    best_thresh, best_f1 = find_best_threshold(all_test_labels, all_test_probs)
    print(f"\n  Global OOF best threshold: {best_thresh:.2f} (F1: {best_f1:.3f})")

    y_pred_oof = (all_test_probs >= best_thresh).astype(int)
    oof_metrics = compute_metrics(all_test_labels, y_pred_oof, all_test_probs, "oof_")

    # Train final model on ALL data
    print("\n  Training final model on all data...")
    rf_final = RandomForestClassifier(**RF_PARAMS)
    rf_final.fit(X, y)

    # Feature importance
    feat_importance = pd.DataFrame({
        'feature': feat_cols,
        'importance': rf_final.feature_importances_
    }).sort_values('importance', ascending=False)
    print(f"\n  Top 10 features:")
    for _, row in feat_importance.head(10).iterrows():
        print(f"    {row['feature']}: {row['importance']:.4f}")

    # Save model + metadata
    model_data = {
        'model': rf_final,
        'features': feat_cols,
        'threshold': best_thresh,
        'oof_metrics': oof_metrics,
        'fold_metrics': fold_metrics,
        'config': {
            'K': K, 'H': H, 'TP_PCT': TP_PCT, 'SL_PCT': SL_PCT,
            'FEE_RATE': FEE_RATE, 'HOLDINGS': HOLDINGS,
            'PURGE_BARS': PURGE_BARS, 'EMBARGO_BARS': EMBARGO_BARS,
            'N_SPLITS': N_SPLITS, 'RF_PARAMS': RF_PARAMS,
        },
        'feature_importance': feat_importance.to_dict('records'),
        'trained_on': str(pd.Timestamp.utcnow()),
        'n_samples': len(X),
    }
    joblib.dump(model_data, MODEL_FILE)
    print(f"\n  Saved model: {MODEL_FILE}")

    # Save metrics
    with open(METRICS_FILE, 'w') as f:
        json.dump({
            'oof_metrics': oof_metrics,
            'fold_metrics': fold_metrics,
            'best_threshold': best_thresh,
            'feature_importance': feat_importance.to_dict('records'),
        }, f, indent=2)
    print(f"  Saved metrics: {METRICS_FILE}")

    # Summary
    print(f"\n=== SUMMARY ===")
    print(f"  Samples: {len(X):,}")
    print(f"  Features: {len(feat_cols)}")
    print(f"  OOF AUC: {oof_metrics['oof_auc']:.3f}")
    print(f"  OOF Accuracy: {oof_metrics['oof_accuracy']:.3f}")
    print(f"  OOF Precision: {oof_metrics['oof_precision']:.3f}")
    print(f"  OOF Recall: {oof_metrics['oof_recall']:.3f}")
    print(f"  Best threshold: {best_thresh:.2f}")
    print(f"  Selected: {y_pred_oof.sum():,} / {len(y_pred_oof):,} ({100*y_pred_oof.mean():.1f}%)")


if __name__ == '__main__':
    main()