"""Config consistency: runner constants MUST match meta-labeler training config.

This guards the Wave 6 lesson: 'registration config field names are part of the
contract' — a silent mismatch between the live runner and the trained model's
feature/labels would make the meta-labeler meaningless.
"""
import alpha3_dry_runner as R
from scripts import meta_labeler_config as MC
from binance_config import ALPHA3_ASSETS


def test_k_horizon_match():
    assert R.K == MC.K == 10
    assert R.H == MC.H == 75


def test_tp_sl_fee_match():
    assert R.WIN_PCT == MC.TP_PCT == 0.02
    assert R.LOSS_PCT == MC.SL_PCT == -0.02
    assert R.FEE_RATE == MC.FEE_RATE == 0.0002


def test_asset_universe_match():
    assert ALPHA3_ASSETS == MC.HOLDINGS


def test_threshold_default_matches():
    # The runner hardcodes 0.50 to match training; flag if it drifts.
    assert R.META_THRESHOLD == 0.50
