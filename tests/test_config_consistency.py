"""Config consistency: runner constants MUST match meta-labeler training config.

This guards the Wave 6 lesson: 'registration config field names are part of the
contract' — a silent mismatch between the live runner and the trained model's
feature/labels would make the meta-labeler meaningless.

K divergence note (2026-08-31 'alpha3learn'): the live runner runs momentum
K=30 while the canonical model artifact (models/meta_labeler.joblib) was
trained at K=10. That divergent state is INTENTIONAL and deferred-retrain —
'test_model_artifact_k_is_10_pending_retrain' locks the artifact at 10 and
will flip to 30 the day the K30 retrain lands.
"""
import joblib

import alpha3_dry_runner as R
from scripts import meta_labeler_config as MC
from binance_config import ALPHA3_ASSETS


def test_k_horizon_match():
    # K reflects the alpha3 LIVE runner contract.
    assert R.K == MC.K == 30
    assert R.H == MC.H == 100


def test_model_artifact_k_is_10_pending_retrain():
    # The canonical model was trained at K=10 (2026-08-29); the K30 retrain is
    # DEFERRED. Until it lands, this artifact (K10) gates K30 entries — the
    # documented divergence this test locks in place.
    model_data = joblib.load(R.META_LABELER_PATH)
    assert model_data["config"]["K"] == 10
    assert model_data["config"]["H"] == MC.H
    assert model_data["threshold"] == R.META_THRESHOLD


def test_tp_sl_fee_match():
    assert R.WIN_PCT == MC.TP_PCT == 0.035
    assert R.LOSS_PCT == MC.SL_PCT == -0.02
    assert R.FEE_RATE == MC.FEE_RATE == 0.0002


def test_asset_universe_match():
    assert ALPHA3_ASSETS == MC.HOLDINGS


def test_threshold_default_matches():
    # The runner hardcodes 0.50 to match training; flag if it drifts.
    assert R.META_THRESHOLD == 0.50
