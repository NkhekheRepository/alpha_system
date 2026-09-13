# Tests

**Scope.** Documents the automated test suite, how to run it, and what each module
guards. The suite is a **green gate**: it must pass on every change (see
`GOVERNANCE.md` deployment-block rules and `RECOMMENDATIONS.md` P3-10).

---

## Run

```bash
cd /home/nkhekhe/alpha_system
python3 -m pytest -q        # 200 passed
# or
make test
```

Configuration: `pytest.ini` sets `testpaths=tests`, `pythonpath=.`,
`addopts=-q`. Tests import project modules directly (repo root on path).

---

## Coverage by Module

| Test file | Guards | Key assertions |
|-----------|--------|----------------|
| `test_config_consistency.py` | `binance_config`, `alpha3_dry_runner`, `meta_labeler_config` | `ALPHA3_ASSETS` == 48; threshold 0.61; model sha 1091b967; API base/keys resolve; demo vs mainnet separation |
| `test_meta_labeler.py` | `scripts/meta_labeler_config`, `scripts/meta_features`, model | K=60, H=100, TP/SL=0.03/-0.015; idx-boundary parity; model loads, threshold 0.61 |
| `test_features.py` | `scripts/meta_features` | `compute_features_at_index` returns 36 features; bootstrap guard; determinism |
| `test_labels.py` | `scripts.generate_labels` | `compute_labels_vectorized` triple-barrier correctness; one exit per label |
| `test_equity.py` | `alpha3_dry_runner.get_effective_equity`, `log_equity` | effective equity = capital + unrealized; CSV header has `effective_equity` |
| `test_demo_trader.py` | `demo_trader` | `round_qty` floor to step; `set_leverage_all` sets 20x; signature HMAC; bracket ordering |
| `test_runner_helpers.py` | `alpha3_dry_runner` | `features_to_array` order matches `FEATURE_ORDER` (36); `default_state` shape; `_sign`; MAX_OPEN_POSITIONS=3 |
| `test_pipeline_e2e.py` | `alpha3_dry_runner.run_cycle`, `meta_features`, `conftest` | Full cycle: bootstrap → signal → meta-filter → entry → barrier → exit; 29 e2e scenarios |
| `test_alpha3_model_consistency.py` | `alpha3_dry_runner`, `meta_features`, `engineer_features`, `alpha4_dry_runner` | Feature parity: runner/live/training EMA/RSI/MACD numerically equal; 36-subset contract |
| `test_alpha4_config_consistency.py` | `alpha4_dry_runner` | Alpha 4 pinned constants (K=40, threshold 0.61 follow-artifact); never revive onto main wallet |

Total: **200 tests, all passing** (run ~20s).

---

## What the Suite Does NOT Cover

- Live network calls to demo-fapi (mocked/omitted by design — `conftest.py` sets
  `TESTNET_LIVE=False` globally; no external dependencies in CI).
- The full 3.0M-row meta-labeler training (validated offline, not in the fast
  suite).
- End-to-end Telegram delivery (bot is exercised manually / via `/status`).
- Bootstrap parse errors on testnet-only symbols (UAIUSDT, ANTHROPICUSDT,
  ZESTUSDT, PONSUSDT) — non-blocking, symbol skipped by runner.

These are intentionally out of the green gate; see `RECOMMENDATIONS.md` P2 for
property-based and chaos tests to extend coverage.

---

## Adding a Test

1. Add a function `test_*` in the relevant `tests/test_*.py` (or a new module).
2. Keep assertions on *observable contracts* (shapes, constants, parity), not
   internal randomness.
3. Run `make test`; keep it green before committing.
