"""Config consistency: runner constants MUST match meta-labeler training config.

This guards the Wave 6 lesson: 'registration config field names are part of the
contract' — a silent mismatch between the live runner and the trained model's
feature/labels would make the meta-labeler meaningless.

K=60 H=100 TP3%/SL1.5% retrain landed (2026-09-07). Runner and model artifact
now both use K=60, H=100, TP=3%, SL=1.5%, FEE=0.05%, 10-symbol universe
(+ZECUSDT).
"""
import joblib

import alpha3_dry_runner as R
from scripts import meta_labeler_config as MC
from binance_config import ALPHA3_ASSETS


def test_k_horizon_match():
    # K reflects the alpha3 LIVE runner contract.
    assert R.K == MC.K == 60
    assert R.H == MC.H == 100
    assert R.INTERVAL == 10  # 10s polls (runner) vs MC.INTERVAL_SEC=60 (meta-labeler 60s bars) — intentionally different
    assert MC.INTERVAL_SEC == 60


def test_model_artifact_k_is_40():
    # K60 H100 TP3/SL1.5 retrain landed (2026-09-07). The canonical model
    # now matches the live runner. This test confirms the artifact is fresh.
    model_data = joblib.load(R.META_LABELER_PATH)
    assert model_data["config"]["K"] == 60
    assert model_data["config"]["H"] == MC.H
    assert model_data["threshold"] == R.META_THRESHOLD
    assert model_data["config"]["TP_PCT"] == 0.03


def test_tp_sl_fee_match():
    assert R.WIN_PCT == MC.TP_PCT == 0.03
    assert R.LOSS_PCT == MC.SL_PCT == -0.015
    assert R.FEE_RATE == MC.FEE_RATE == 0.0005


def test_asset_universe_match():
    assert ALPHA3_ASSETS == MC.HOLDINGS


def test_threshold_default_matches():
    # Set to 0.60 (2026-09-07): breakeven 34.4% @TP3/SL1.5, in-sample prec 0.46.
    # Model artifact, runner, and config must agree; flag if they drift.
    model_data = joblib.load(R.META_LABELER_PATH)
    assert model_data["threshold"] == 0.60
    assert R.META_THRESHOLD == 0.60
    assert MC.PROB_THRESHOLD_DEFAULT == 0.60
