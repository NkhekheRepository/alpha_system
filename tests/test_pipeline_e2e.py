"""End-to-end Alpha 3 pipeline integration tests.

Drives run_cycle through the WHOLE pipeline with a fully mocked, deterministic
price feed (no network, no Telegram, no production ledgers — conftest redirects
all side-effect sinks to tmp_path):

  ingestion -> bootstrap/continuous hist (dedup) -> exit eval (TP/SL/TIMEOUT,
  direction-correct) -> circuit breaker -> cooldown -> entry (momentum +
  meta-labeler filter + sizing) -> ledger (capital/equity/drawdown/CSV) ->
  atomic save/load -> reconcile.

These guard the verified Wave lessons encoded in the engine:
  * W10: runner-side exit evaluation with per-cycle live prices, direction correct.
  * Atomic save_state (no truncate-in-place -> no corrupt JSON -> no silent reset).
  * In-bucket dedup of the not-yet-closed 1m bar.
  * Exits always evaluated even during cooldown; cooldown gates entries only.
  * Meta-labeler filter gates entries (prob < threshold -> SKIP).
"""

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

import alpha3_dry_runner as R

SINGLE = "BTRUSDT"


class PriceFeeder:
    """A scriptable fake data source: cycle / asset -> dict OHLV."""

    def __init__(self, scripts, start=100.0, base_time=None):
        self.scripts = {s: list(v) for s, v in scripts.items()}
        self.cursor = {s: 0 for s in self.scripts}
        self.start = start
        self.base_time = base_time or datetime(2026, 8, 30, 6, 0, 0)

    def _price(self, symbol):
        seq = self.scripts.get(symbol)
        if seq is None:
            return self.start
        i = min(self.cursor.get(symbol, 0), len(seq) - 1)
        self.cursor[symbol] = i + 1
        return seq[i]

    def ohlcv(self, symbol):
        p = self._price(symbol)
        return {
            "open": p, "high": p, "low": p, "close": p, "volume": 1000.0,
            "close_time": int(self.base_time.timestamp() // 60),
        }

    def _now_ts(self):
        return int(self.base_time.timestamp())


def _make_state(n_hist=200, capital=100.0, start_price=100.0):
    """A state pre-bootstrapped with n_hist identical bars so momentum is live."""
    state = R.default_state()
    state["start_capital"] = capital
    state["capital"] = capital
    state["equity"] = capital
    state["effective_equity"] = capital
    state["peak_equity"] = capital
    state["trading_enabled"] = True
    state["stake_pct"] = 0.03
    state["leverage"] = 20.0
    bar = {"open": start_price, "high": start_price, "low": start_price,
           "close": start_price, "volume": 1000.0, "close_time": 0}
    for s in R.ASSETS:
        state["price_history"][s] = [dict(bar) for _ in range(n_hist)]
    # Ensure the single test asset exists even if ASSETS is later pinned.
    if SINGLE not in state["price_history"]:
        state["price_history"][SINGLE] = [dict(bar) for _ in range(n_hist)]
    return state


# ---------------------------------------------------------------------------
# Stage 1+2+3: ingestion, history append, dedup
# ---------------------------------------------------------------------------
class TestHistoryIngestionDedup:
    def test_append_new_bar_distinct_close_time(self, monkeypatch):
        # Seed with 199 so a distinct bucket should grow to 200 (cap not hit).
        state = _make_state(n_hist=199)
        feeder = PriceFeeder({}, base_time=datetime(2026, 8, 30, 6, 0, 0))
        bars = []

        def fake_ohlcv(symbol):
            p = feeder.start
            ct = len(bars) + 1
            bars.append(ct)
            return {"open": p, "high": p, "low": p, "close": p,
                    "volume": 1000.0, "close_time": ct}

        monkeypatch.setattr(R, "get_ohlcv", fake_ohlcv)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        # Suppress entry so we only test history mechanics.
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)

        hist_before = len(state["price_history"][SINGLE])
        assert hist_before == 199
        R.run_cycle(state, meta_model=None)
        assert len(state["price_history"][SINGLE]) == 200
        assert hist_before + 1 == 200

    def test_duplicate_close_time_replaces_in_place(self, monkeypatch):
        # Seed with 199 so first distinct append grows to 200, second duplicate stays.
        state = _make_state(n_hist=199)
        n_before = len(state["price_history"][SINGLE])
        assert n_before == 199

        def fake_ohlcv(symbol):
            return {"open": 100, "high": 101, "low": 99, "close": 100.5,
                    "volume": 500.0, "close_time": 999000}

        monkeypatch.setattr(R, "get_ohlcv", fake_ohlcv)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)

        R.run_cycle(state, meta_model=None)
        R.run_cycle(state, meta_model=None)

        hist = state["price_history"][SINGLE]
        assert len(hist) == n_before + 1 == 200
        assert hist[-1]["close"] == 100.5

    def test_history_capped_at_200(self, monkeypatch):
        state = _make_state(n_hist=200)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)

        calls = {"n": 0}

        def fake_ohlcv(symbol):
            calls["n"] += 1
            return {"open": 100, "high": 100, "low": 100, "close": 100,
                    "volume": 1.0, "close_time": calls["n"] + 1000000}

        monkeypatch.setattr(R, "get_ohlcv", fake_ohlcv)

        R.run_cycle(state, meta_model=None)
        # History is capped at 200; the runner slices to [-200:] which reassigns
        # the list, so we must check the current state entry, not a stale ref.
        assert len(state["price_history"][SINGLE]) == 200
        assert len(state["price_history"][SINGLE]) <= 200


# ---------------------------------------------------------------------------
# Stage 4: exit evaluation — direction-correct TP / SL, timeout, during cooldown
# ---------------------------------------------------------------------------
class TestExitEvaluation:
    def _run_with_price(self, monkeypatch, price, entry_price=100.0, direction="long",
                        cooldown=0, age=None, close_time=777000):
        state = _make_state(capital=100.0, start_price=100.0)
        state["open_positions"][SINGLE] = {
            "symbol": SINGLE, "direction": direction,
            "entry_price": entry_price, "quantity": 1.0, "notional": 100.0,
            "age": age if age is not None else 0,
            "tp_price": entry_price * (0.975 if direction == "short" else 1.025),
            "sl_price": entry_price * (1.02 if direction == "short" else 0.98),
            "entry_time": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
        }
        state["cooldown_remaining"] = cooldown

        def fake_ohlcv(symbol):
            return {"open": 100, "high": price, "low": price, "close": price,
                    "volume": 1.0, "close_time": close_time}

        monkeypatch.setattr(R, "get_ohlcv", fake_ohlcv)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        # Prevent re-entry after the exit so we can assert the close in isolation.
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)
        return R.run_cycle(state, meta_model=None)

    def test_long_tp_direction_correct(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=104.0, direction="long")
        assert SINGLE not in state["open_positions"]
        assert len(state["trades"]) == 1
        t = state["trades"][0]
        assert t["reason"] == "TP"
        assert t["direction"] == "long"
        assert t["pnl_dollars"] > 0

    def test_long_sl_direction_correct(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=97.0, direction="long")
        assert SINGLE not in state["open_positions"]
        t = state["trades"][0]
        assert t["reason"] == "SL"
        assert t["pnl_dollars"] < 0

    def test_short_tp_direction_correct(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=95.0, direction="short")
        assert SINGLE not in state["open_positions"]
        t = state["trades"][0]
        assert t["reason"] == "TP"
        assert t["pnl_dollars"] > 0

    def test_short_sl_direction_correct(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=103.0, direction="short")
        assert SINGLE not in state["open_positions"]
        t = state["trades"][0]
        assert t["reason"] == "SL"
        assert t["pnl_dollars"] < 0

    def test_trade_pnl_sign_matches_dir_win(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=104.0, direction="long")
        assert state["total_wins"] == 1
        assert state["total_losses"] == 0

    def test_timeout_after_h_bars(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=100.0, direction="long", age=R.H)
        assert SINGLE not in state["open_positions"]
        t = state["trades"][0]
        assert t["reason"] == "TIMEOUT"
        assert t["exit_price"] == 100.0
        assert t["pnl_dollars"] < 0  # fees make flat exit a small loss

    def test_no_exit_before_h_when_within_barriers(self, monkeypatch):
        state = self._run_with_price(monkeypatch, price=101.0, direction="long", age=5)
        assert SINGLE in state["open_positions"]
        assert state["trades"] == []

    def test_exits_eval_during_cooldown(self, monkeypatch):
        # Cooldown gates ENTRIES only; open position must still close on TP.
        state = self._run_with_price(monkeypatch, price=104.0, direction="long", cooldown=10)
        assert SINGLE not in state["open_positions"]
        assert len(state["trades"]) == 1


# ---------------------------------------------------------------------------
# Stage 5+6: circuit breaker + cooldown gating
# ---------------------------------------------------------------------------
class TestCircuitBreakerCooldown:
    def test_three_losses_trigger_cooldown(self, monkeypatch):
        state = _make_state()
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)

        for i in range(3):
            state["open_positions"][SINGLE] = {
                "symbol": SINGLE, "direction": "long",
                "entry_price": 100.0, "quantity": 1.0, "notional": 100.0,
                "age": 0, "tp_price": 103.5, "sl_price": 98.0,
                "entry_time": datetime.utcnow().isoformat(),
            }

            def fake_ohlcv(symbol, _p=97.0, _i=i):
                return {"open": 100, "high": _p, "low": _p, "close": _p,
                        "volume": 1.0, "close_time": 100000 + _i}

            monkeypatch.setattr(R, "get_ohlcv", fake_ohlcv)
            R.run_cycle(state, meta_model=None)

        assert state["consecutive_losses"] == 0  # reset after trigger
        # Trigger happens inside exit handling (sets 50), then the same cycle's
        # cooldown gate decrements once -> 49 remaining post-cycle.
        assert state["cooldown_remaining"] == R.COOLDOWN - 1

    def test_cooldown_blocks_entries_but_state_keeps_prices(self, monkeypatch):
        state = _make_state()
        state["cooldown_remaining"] = 5
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": 100, "low": 100, "close": 100,
            "volume": 1.0, "close_time": 555000})
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "momentum_direction", lambda ph: "long")
        R.run_cycle(state, meta_model=None)
        assert state["open_positions"] == {}       # no new entries
        assert state["cooldown_remaining"] == 4     # decrement happens


# ---------------------------------------------------------------------------
# Stage 7: entry logic — momentum + meta-labeler filter
# ---------------------------------------------------------------------------
class TestEntryLogic:
    def _entry_cycle(self, monkeypatch, meta_model=None, meta_threshold=R.META_THRESHOLD):
        state = _make_state(capital=100.0, start_price=100.0)
        # Build a strictly increasing history so momentum is deterministically LONG.
        hist = state["price_history"][SINGLE]
        for j in range(len(hist)):
            hist[j]["close"] = 80.0 + j * 0.1  # 80 .. ~100, monotonic up
            hist[j]["open"] = hist[j]["close"]
            hist[j]["high"] = hist[j]["close"]
            hist[j]["low"] = hist[j]["close"]
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": 100, "low": 100, "close": 100.0,
            "volume": 1.0, "close_time": 900000})
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        return R.run_cycle(state, meta_model=meta_model, meta_threshold=meta_threshold)

    def test_momentum_direction(self):
        ph = [{"close": float(i)} for i in range(50)]
        assert R.momentum_direction(ph) == "long"
        ph2 = [{"close": float(100 - i)} for i in range(50)]
        assert R.momentum_direction(ph2) == "short"
        assert R.momentum_direction([{"close": 1.0}]) is None

    def test_entry_opened_when_momentum_present(self, monkeypatch):
        state = self._entry_cycle(monkeypatch, meta_model=None)
        assert len(state["open_positions"]) == 1
        sym, pos = next(iter(state["open_positions"].items()))
        assert pos["direction"] == "long"
        assert pos["tp_price"] == pytest.approx(pos["entry_price"] * 1.025)
        assert pos["sl_price"] == pytest.approx(pos["entry_price"] * 0.98)

    def test_trading_disabled_blocks_entry(self, monkeypatch):
        # Build state with increasing history but trading disabled -> no entry.
        state = _make_state(capital=100.0, start_price=100.0)
        hist = state["price_history"][SINGLE]
        for j in range(len(hist)):
            hist[j]["close"] = 80.0 + j * 0.1
        state["trading_enabled"] = False
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": 100, "low": 100, "close": 100.0,
            "volume": 1.0, "close_time": 900001})
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        R.run_cycle(state, meta_model=None)
        assert state["open_positions"] == {}


# ---------------------------------------------------------------------------
# Stage 8: ledger / equity / trade log consistency + atomic save/load
# ---------------------------------------------------------------------------
class TestLedgerAndPersistence:
    def test_closed_trade_updates_capital_equity_and_csv(self, monkeypatch, tmp_path):
        state = _make_state(capital=100.0)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "TRADE_LOG", tmp_path / "trades.csv")
        monkeypatch.setattr(R, "EQUITY_LOG", tmp_path / "equity.csv")
        state["open_positions"][SINGLE] = {
            "symbol": SINGLE, "direction": "long", "entry_price": 100.0,
            "quantity": 1.0, "notional": 100.0, "age": 0,
            "tp_price": 103.5, "sl_price": 98.0,
            "entry_time": datetime.utcnow().isoformat(),
        }
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": 104, "low": 104, "close": 104.0,
            "volume": 1.0, "close_time": 700000})
        R.run_cycle(state, meta_model=None)

        assert state["total_trades"] == 1
        assert state["total_wins"] == 1
        assert state["capital"] > 100.0
        assert pytest.approx(state["equity"]) == state["capital"]
        assert (tmp_path / "trades.csv").exists()

    def test_save_load_round_trip_preserves_state(self, tmp_path, monkeypatch):
        s1 = _make_state(capital=123.0)
        s1["total_trades"] = 7
        s1["total_wins"] = 5
        s1["total_losses"] = 2
        new_state = tmp_path / "state.json"
        monkeypatch.setattr(R, "STATE_FILE", new_state)
        monkeypatch.setattr(R, "DATA_DIR", tmp_path)
        R.save_state(s1)

        assert new_state.exists()
        loaded = json.loads(new_state.read_text())
        assert loaded["capital"] == 123.0
        assert loaded["total_trades"] == 7
        assert list(tmp_path.glob("*.tmp")) == []
        for key in ("capital", "equity", "peak_equity", "open_positions",
                    "total_trades", "total_wins", "total_losses",
                    "cooldown_remaining", "price_history"):
            assert key in loaded


# ---------------------------------------------------------------------------
# Stage 9: reconcile paper-close on demo-flat (paper = source of truth)
# ---------------------------------------------------------------------------
class TestReconcile:
    def test_reconcile_closes_paper_when_demo_flat(self, monkeypatch, tmp_path):
        state = _make_state(capital=100.0)
        state["open_positions"][SINGLE] = {
            "symbol": SINGLE, "direction": "long", "entry_price": 100.0,
            "quantity": 1.0, "notional": 100.0, "age": 0,
            "tp_price": 103.5, "sl_price": 98.0,
            "entry_time": datetime.utcnow().isoformat(),
        }
        monkeypatch.setattr(R, "DEMO_LIVE", True)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "TRADE_LOG", tmp_path / "trades.csv")
        monkeypatch.setattr(R, "get_price", lambda s: 105.0)
        monkeypatch.setattr(R, "_signed_get", lambda *a, **k: [])
        monkeypatch.setattr(R, "STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(R, "DATA_DIR", tmp_path)

        R.reconcile_on_startup(state)
        assert SINGLE not in state["open_positions"]
        assert len(state["trades"]) == 1
        assert state["trades"][0]["reason"] == "RECONCILE"
        assert state["capital"] > 100.0

    def test_reconcile_never_fails_on_api_error(self, monkeypatch, tmp_path):
        state = _make_state(capital=100.0)
        state["open_positions"][SINGLE] = {
            "symbol": SINGLE, "direction": "long", "entry_price": 100.0,
            "quantity": 1.0, "notional": 100.0, "age": 0,
            "tp_price": 103.5, "sl_price": 98.0,
            "entry_time": datetime.utcnow().isoformat(),
        }
        monkeypatch.setattr(R, "DEMO_LIVE", True)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "_signed_get", lambda *a, **k: None)
        monkeypatch.setattr(R, "get_price", lambda s: 105.0)
        R.reconcile_on_startup(state)
        assert SINGLE in state["open_positions"]
        assert state["trades"] == []

    def test_reconcile_noop_when_not_demo_live(self, monkeypatch, tmp_path):
        state = _make_state(capital=100.0)
        state["open_positions"][SINGLE] = {
            "symbol": SINGLE, "direction": "long", "entry_price": 100.0,
            "quantity": 1.0, "notional": 100.0, "age": 0,
            "tp_price": 103.5, "sl_price": 98.0,
            "entry_time": datetime.utcnow().isoformat(),
        }
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        R.reconcile_on_startup(state)
        assert SINGLE in state["open_positions"]
        assert state["trades"] == []

    def test_reconcile_sweeps_orphan_demo_leg(self, monkeypatch, tmp_path):
        """A demo position with no paper leg -> reduce-only market close (orphan)."""
        import demo_trader
        record = {}
        monkeypatch.setattr(R, "DEMO_LIVE", True)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(R, "TRADE_LOG", tmp_path / "trades.csv")
        monkeypatch.setattr(R, "_signed_get", lambda *a, **k: [
            {"symbol": SINGLE, "positionAmt": "0.25"},
        ])
        monkeypatch.setattr(demo_trader, "cancel_algo_orders", lambda s: None)
        monkeypatch.setattr(demo_trader, "round_qty", lambda s, q: q)
        monkeypatch.setattr(
            demo_trader, "place_market_order",
            lambda s, side, qty, reduce_only=False: (
                record.update(side=side, qty=qty, reduce_only=reduce_only), {"filled": True}, None)[1])
        state = _make_state(capital=100.0)  # no paper positions
        R.reconcile_on_startup(state)
        assert record == {"side": "SELL", "qty": 0.25, "reduce_only": True}
        assert state["trades"] == []  # orphan sweep is not a paper trade


# ---------------------------------------------------------------------------
# Stage 4b extension: PnL is position-size respecting + fee-inclusive (W9-bug
# regression guard for Alpha 3).
# ---------------------------------------------------------------------------
class TestPnlCorrectness:
    def _unit_position(self, qty, entry=100.0, tp=103.5):
        return {
            "symbol": SINGLE, "direction": "long",
            "entry_price": entry, "quantity": qty, "notional": qty * entry,
            "age": 1, "tp_price": tp, "sl_price": 98.0,
            "entry_time": (datetime.utcnow() - timedelta(minutes=1)).isoformat(),
        }

    def _run_tp(self, monkeypatch, qty, entry=100.0, tp=103.5):
        state = _make_state(capital=100.0, start_price=entry)
        state["open_positions"][SINGLE] = self._unit_position(qty, entry, tp)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": tp, "low": tp, "close": tp,
            "volume": 1.0, "close_time": 700000})
        R.run_cycle(state, meta_model=None)
        return state["trades"][0]

    def test_pnl_matches_position_size_and_fee(self, monkeypatch):
        t = self._run_tp(monkeypatch, qty=1.0)
        assert t["reason"] == "TP"
        entry, tp, qty = 100.0, 103.5, 1.0
        expected = qty * (tp - entry) - qty * (entry + tp) * R.FEE_RATE
        assert t["pnl_dollars"] == pytest.approx(expected, abs=1e-9)
        # Regression guard: NOT the bugged 100% notional form
        assert t["pnl_dollars"] != pytest.approx(100000.0 * (tp - entry) / entry, abs=1e-3)
        assert t["pnl_dollars"] < 100.0

    def test_pnl_scales_with_quantity(self, monkeypatch):
        p1 = self._run_tp(monkeypatch, qty=1.0)["pnl_dollars"]
        p2 = self._run_tp(monkeypatch, qty=2.0)["pnl_dollars"]
        assert p2 == pytest.approx(2.0 * p1, rel=1e-6)


# ---------------------------------------------------------------------------
# Stage 7 extension: sizing / leverage and the LEV_OVERRIDE cap
#
# Alpha 3 sizing semantics (alpha3_dry_runner.py:852-854):
#     eff_lev   = LEV_OVERRIDE.get(s, state['leverage'])
#     pos_val   = state['capital'] * state['stake_pct'] * eff_lev
#     qty       = pos_val / prices[s]
# The state's stake_pct/leverage are live DB fields (not module constants).
# _make_state seeds stake_pct=0.03, leverage=20.0, capital=$100.
# ---------------------------------------------------------------------------
class TestSizingLeverage:
    def _monotonic_up(self, state, symbol):
        hist = state["price_history"][symbol]
        for j in range(len(hist)):
            hist[j]["close"] = 80.0 + j * 0.1
            hist[j]["open"] = hist[j]["close"]
            hist[j]["high"] = hist[j]["close"]
            hist[j]["low"] = hist[j]["close"]

    def _enter(self, monkeypatch, symbol, close=100.0):
        state = _make_state(capital=100.0, start_price=100.0)
        self._monotonic_up(state, symbol)
        monkeypatch.setattr(R, "ASSETS", [symbol])
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "get_ohlcv", lambda s, _c=close: {
            "open": 100, "high": _c, "low": _c, "close": _c,
            "volume": 1.0, "close_time": 900000})
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        R.run_cycle(state, meta_model=None)
        return state["open_positions"][symbol]

    def test_sizing_stake_and_leverage(self, monkeypatch):
        # no override: eff_lev = state.leverage = 20 -> 100 * 0.03 * 20 = 60
        pos = self._enter(monkeypatch, SINGLE)
        assert pos["notional"] == pytest.approx(100.0 * 0.03 * 20.0)
        assert pos["quantity"] == pytest.approx(60.0 / 100.0)
        assert pos["notional"] == pytest.approx(
            pos["quantity"] * pos["entry_price"], rel=1e-9)

    def test_lev_override_caps_effective_leverage(self, monkeypatch):
        # BICOUSDT is capped to 10x by LEV_OVERRIDE (state lev 20 -> 10).
        bico = "BICOUSDT"
        eff = R.LEV_OVERRIDE.get(bico)
        assert eff is not None
        assert eff < 20.0
        pos = self._enter(monkeypatch, bico)
        assert pos["notional"] == pytest.approx(100.0 * 0.03 * eff)
        assert pos["quantity"] == pytest.approx(pos["notional"] / 100.0)


# ---------------------------------------------------------------------------
# Stage 7 extension: meta-labeler probe — prob < threshold skips, >= enters
# ---------------------------------------------------------------------------
class TestMetaLabelerFilterProbe:
    class LowProbe:
        def predict_proba(self, x):
            return np.array([[0.7, 0.1]])

    class HighProbe:
        def predict_proba(self, x):
            return np.array([[0.1, 0.9]])

    def _entry_cycle(self, monkeypatch, meta_model=None,
                     meta_threshold=R.META_THRESHOLD):
        state = _make_state(capital=100.0, start_price=100.0)
        hist = state["price_history"][SINGLE]
        for j in range(len(hist)):
            hist[j]["close"] = 80.0 + j * 0.1
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": 100, "low": 100, "close": 100.0,
            "volume": 1.0, "close_time": 900000})
        monkeypatch.setattr(R, "get_orderbook", lambda s: None)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        return R.run_cycle(state, meta_model=meta_model, meta_threshold=meta_threshold)

    def test_low_probability_entry_is_filtered(self, monkeypatch):
        state = self._entry_cycle(monkeypatch, meta_model=self.LowProbe(),
                                  meta_threshold=0.5)
        assert SINGLE not in state["open_positions"]
        assert state["trades"] == []

    def test_high_probability_entry_passes(self, monkeypatch):
        state = self._entry_cycle(monkeypatch, meta_model=self.HighProbe(),
                                  meta_threshold=0.5)
        assert SINGLE in state["open_positions"]


# ---------------------------------------------------------------------------
# Stage 2 extension: orderbook history micro-feature ring append + cap
# ---------------------------------------------------------------------------
class TestOrderbookHistory:
    def test_orderbook_appends_and_caps_at_200(self, monkeypatch):
        state = _make_state(n_hist=200)
        monkeypatch.setattr(R, "DEMO_LIVE", False)
        monkeypatch.setattr(R, "ASSETS", [SINGLE])
        monkeypatch.setattr(R, "momentum_direction", lambda ph: None)
        monkeypatch.setattr(R, "get_ohlcv", lambda s: {
            "open": 100, "high": 100, "low": 100, "close": 100,
            "volume": 1.0, "close_time": 900000})
        calls = {"n": 0}

        def fake_ob(symbol):
            calls["n"] += 1
            return {"bid": 99.0, "ask": 100.0, "seq": calls["n"]}

        monkeypatch.setattr(R, "get_orderbook", fake_ob)
        state["orderbook_history"] = {SINGLE: [{"bid": 0.0} for _ in range(200)]}
        R.run_cycle(state, meta_model=None)
        R.run_cycle(state, meta_model=None)
        ob = state["orderbook_history"][SINGLE]
        assert len(ob) <= 200
        assert ob[-1]["seq"] == calls["n"]
