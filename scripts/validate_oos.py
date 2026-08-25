#!/usr/bin/env python3
"""OOS walk-forward validation for meta-labeler.

Expanding window: train on first T months, test on next 1 month, repeat.
This simulates real deployment where model is retrained monthly.

Usage:
    python3 scripts/validate_oos.py
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
    PURGE_BARS, EMBARGO_BARS, MIN_TRADES_PER_FOLD,
    RF_PARAMS, PROB_THRESHOLD_DEFAULT
)

FEATURE_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_features.csv'
MODEL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'meta_labeler.joblib'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'oos_validation_results.json'


def compute_metrics(y_true, y_pred, y_prob, prefix=""):
    return {
        f"{prefix}auc": float(roc_auc_score(y_true, y_prob)),
        f"{prefix}accuracy": float(accuracy_score(y_true, y_pred)),
        f"{prefix}precision": float(precision_score(y_true, y_pred)),
        f"{prefix}recall": float(recall_score(y_true, y_pred)),
        f"{prefix}n_samples": int(len(y_true)),
        f"{prefix}n_positive": int(y_true.sum()),
        f"{prefix}n_negative": int((1 - y_true).sum()),
        f"{prefix}selected": int(y_pred.sum()),
        f"{prefix}selection_rate": float(y_pred.mean()),
    }


def find_best_threshold(y_true, y_prob, thresholds=np.linspace(0.5, 0.9, 9)):
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
    df = pd.read_csv(FEATURE_FILE)
    print(f"Loaded {len(df):,} samples")

    exclude = ['time_idx', 'symbol', 'direction', 'entry_price', 'label', 'barrier_bar']
    feat_cols = [c for c in df.columns if c not in exclude]

    X = df[feat_cols].values.astype(np.float32)
    y = df['label'].values.astype(np.int32)

    # Time-based split: expanding window with monthly test periods
    n_total = len(X)
    n_months = 6
    month_size = n_total // n_months

    results = []
    all_test_probs = []
    all_test_labels = []
    all_test_preds = []

    for month in range(1, n_months):
        train_end = month * month_size
        test_start = train_end
        test_end = min((month + 1) * month_size, n_total)

        X_train, y_train = X[:train_end], y[:train_end]
        X_test, y_test = X[test_start:test_end], y[test_start:test_end]

        print(f"\n  Month {month}: train={len(X_train):,} test={len(X_test):,}")

        if len(X_test) < MIN_TRADES_PER_FOLD:
            print(f"    SKIP: test too small")
            continue

        # Train
        rf = RandomForestClassifier(**RF_PARAMS)
        rf.fit(X_train, y_train)

        # Predict
        test_prob = rf.predict_proba(X_test)[:, 1]

        # Use fixed threshold 0.5 (from CV)
        threshold = 0.50
        y_pred = (test_prob >= threshold).astype(int)

        metrics = compute_metrics(y_test, y_pred, test_prob, f"month{month}_")
        metrics['threshold'] = threshold
        metrics['month'] = month
        results.append(metrics)

        all_test_probs.extend(test_prob)
        all_test_labels.extend(y_test)
        all_test_preds.extend(y_pred)

        print(f"    AUC: {metrics[f'month{month}_auc']:.3f}, "
              f"Acc: {metrics[f'month{month}_accuracy']:.3f}, "
              f"Prec: {metrics[f'month{month}_precision']:.3f}, "
              f"Rec: {metrics[f'month{month}_recall']:.3f}, "
              f"Sel: {metrics[f'month{month}_selection_rate']*100:.1f}%")

    # Aggregate across all test months
    all_test_probs = np.array(all_test_probs)
    all_test_labels = np.array(all_test_labels)
    all_test_preds = np.array(all_test_preds)

    # Overall with threshold 0.5
    overall = compute_metrics(all_test_labels, all_test_preds, all_test_probs, "overall_")

    # Also test with model's threshold
    model_data = joblib.load(MODEL_FILE)
    best_thresh = model_data.get('threshold', 0.5)
    y_pred_model = (all_test_probs >= best_thresh).astype(int)
    overall_model = compute_metrics(all_test_labels, y_pred_model, all_test_probs, f"thresh{best_thresh:.2f}_")

    print(f"\n=== OOS WALK-FORWARD SUMMARY ===")
    for r in results:
        m = r
        month = m['month']
        print(f"  Month {month}: AUC={m[f'month{month}_auc']:.3f}, "
              f"Prec={m[f'month{month}_precision']:.3f}, "
              f"Rec={m[f'month{month}_recall']:.3f}, "
              f"Sel={m[f'month{month}_selection_rate']*100:.1f}%")

    print(f"\n  Overall (thresh=0.50): AUC={overall['overall_auc']:.3f}, "
          f"Acc={overall['overall_accuracy']:.3f}, "
          f"Prec={overall['overall_precision']:.3f}, "
          f"Rec={overall['overall_recall']:.3f}, "
          f"Sel={overall['overall_selection_rate']*100:.1f}%")

    print(f"  Overall (thresh={best_thresh:.2f}): "
          f"AUC={overall_model[f'thresh{best_thresh:.2f}_auc']:.3f}, "
          f"Prec={overall_model[f'thresh{best_thresh:.2f}_precision']:.3f}, "
          f"Sel={overall_model[f'thresh{best_thresh:.2f}_selection_rate']*100:.1f}%")

    # Compare to raw (no filter)
    raw_wr = 100 * all_test_labels.mean()
    filtered_wr = 100 * overall_model[f'thresh{best_thresh:.2f}_precision']
    print(f"\n  Raw WR: {raw_wr:.1f}% -> Filtered WR: {filtered_wr:.1f}% (+{filtered_wr - raw_wr:.1f}pp)")

    # Save
    with open(OUT_FILE, 'w') as f:
        json.dump({
            'monthly': results,
            'overall_threshold_050': overall,
            f'overall_threshold_{best_thresh:.2f}': overall_model,
            'raw_wr': raw_wr,
            'filtered_wr': filtered_wr,
            'improvement_pp': filtered_wr - raw_wr,
        }, f, indent=2)
    print(f"\nSaved: {OUT_FILE}")


if __name__ == '__main__':
    main()