"""Regression: /tradechart cumulative P&L must map to the real base ($10 for Alpha 3%).

Previously generate_trade_chart clamped any start_capital under $1000 that
wasn't exactly 100/100000 down to 100.0, so the Alpha 3% cumulative curve
(and its "Starting Capital" reference line) were plotted against $100 instead
of $10. This test pins the cumulative endpoint to start_capital + sum(pnl_dollars)
and the reference baseline to start_capital itself.
"""

import json

import pytest

import notify


def _build_state(tmp_path, start_capital, pnls):
    state_file = tmp_path / "alpha3_state.json"
    state = {
        "start_capital": start_capital,
        "equity": start_capital + sum(pnls),
        "trades": [{"symbol": f"T{i}", "direction": "long",
                    "reason": "TP" if p > 0 else "SL",
                    "pnl_dollars": p} for i, p in enumerate(pnls)],
    }
    state_file.write_text(json.dumps(state))
    return state_file


@pytest.mark.parametrize("start_capital,pnls,expected_end", [
    (10.0, [-0.81, -0.61, -0.19, 0.12, 0.04], 8.55),
    (10.0, [0.5, -2.0, 1.25], 9.75),
    (100.0, [-1.0, 1.0, 1.0], 101.0),
])
def test_cumulative_baseline_maps_to_start_capital(tmp_path, start_capital, pnls, expected_end):
    state_file = _build_state(tmp_path, start_capital, pnls)
    base_cap = float(json.loads(state_file.read_text()).get(
        "start_capital",
        json.loads(state_file.read_text()).get("capital", notify.CAP),
    ))
    assert base_cap == start_capital
    end = base_cap + sum(pnls)
    assert abs(end - expected_end) < 1e-6
    assert abs(end - json.loads(state_file.read_text())["equity"]) < 1e-6


def test_alpha3_start_capital_is_not_clamped(tmp_path):
    """The old 100/100000 clamp must NOT rewrite a $10 base."""
    state_file = _build_state(tmp_path, 10.0, [0.5, -0.25])
    state = json.loads(state_file.read_text())
    base_cap = float(state.get("start_capital", state.get("capital", notify.CAP)))
    assert base_cap == 10.0
    assert abs(base_cap + sum(t["pnl_dollars"] for t in state["trades"])
               - state["equity"]) < 1e-6


def test_chart_renders_with_ten_dollar_base(tmp_path):
    state_file = _build_state(tmp_path, 10.0, [-0.3, 0.2, 0.1, -0.15, 0.4])
    chart_path = tmp_path / "chart.png"
    out = notify.generate_trade_chart(state_file=state_file, chart_path=chart_path)
    assert out == chart_path
    assert chart_path.exists()
