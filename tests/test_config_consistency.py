"""Config consistency: runner constants MUST match meta-labeler training config.

This guards the Wave 6 lesson: 'registration config field names are part of the
contract' — a silent mismatch between the live runner and the trained model's
feature/labels would make the meta-labeler meaningless.

K=30 retrain landed (2026-09-04). Runner and model artifact now both use
K=30, H=75, TP=2.5%, SL=2%, FEE=0.05%, new 6-symbol universe.
"""
import joblib

import alpha3_dry_runner as R
from scripts import meta_labeler_config as MC
from binance_config import ALPHA3_ASSETS


def test_k_horizon_match():
    # K reflects the alpha3 LIVE runner contract.
    assert R.K == MC.K == 30
    assert R.H == MC.H == 75
    assert R.INTERVAL == 10  # 10s polls (runner) vs MC.INTERVAL_SEC=60 (meta-labeler 60s bars) — intentionally different
    assert MC.INTERVAL_SEC == 60


def test_model_artifact_k_is_10_pending_retrain():
    # K30 retrain landed (2026-09-04). The canonical model now matches
    # the live runner K=30. This test confirms the artifact is fresh.
    model_data = joblib.load(R.META_LABELER_PATH)
    assert model_data["config"]["K"] == 30
    assert model_data["config"]["H"] == MC.H
    assert model_data["threshold"] == R.META_THRESHOLD
    assert model_data["config"]["TP_PCT"] == 0.025


def test_tp_sl_fee_match():
    assert R.WIN_PCT == MC.TP_PCT == 0.025
    assert R.LOSS_PCT == MC.SL_PCT == -0.02
    assert R.FEE_RATE == MC.FEE_RATE == 0.0005


def test_asset_universe_match():
    assert ALPHA3_ASSETS == MC.HOLDINGS


def test_threshold_default_matches():
    # The runner hardcodes 0.50 to match training; flag if it drifts.
    assert R.META_THRESHOLD == 0.50
