# Tests

**Scope.** Documents the automated test suite, how to run it, and what each module
guards. The suite is a **green gate**: it must pass on every change (see
`GOVERNANCE.md` deployment-block rules and `RECOMMENDATIONS.md` P3-10).

---

## Run

```bash
cd /home/nkhekhe/alpha_system
python3 -m pytest -q        # 27 passed
# or
make test
```

Configuration: `pytest.ini` sets `testpaths=tests`, `pythonpath=.`,
`addopts=-q`. Tests import project modules directly (repo root on path).

---

## Coverage by Module

| Test file | Guards | Key assertions |
|-----------|--------|----------------|
| `test_config_consistency.py` | `binance_config` | `ALPHA3_ASSETS` == 6; API base/keys resolve; demo vs mainnet separation |
| `test_meta_labeler.py` | `scripts/meta_labeler_config`, `scripts/meta_features`, model | K=10, H=75, TP/CT=0.02, SL_PCT=-0.02; idx-boundary 199/200 parity; model loads, threshold 0.50 |
| `test_features.py` | `scripts/meta_features` | `compute_features_at_index` returns 36 features; bootstrap guard; determinism |
| `test_labels.py` | `scripts/generate_labels` | `compute_labels_vectorized` triple-barrier correctness; one exit per label |
| `test_equity.py` | `alpha3_dry_runner.get_effective_equity`, `log_equity` | effective equity = capital + unrealized; CSV header has `effective_equity` |
| `test_demo_trader.py` | `demo_trader` | `round_qty` floor to step; `set_leverage_all` sets 50x; signature HMAC; bracket ordering |
| `test_runner_helpers.py` | `alpha3_dry_runner` | `features_to_array` order matches `FEATURE_ORDER` (36); `default_state` shape; `_sign` |

Total: **27 tests, all passing** (run 12.20s).

---

## What the Suite Does NOT Cover

- Live network calls to demo-fapi (mocked/omitted by design — no external
  dependencies in CI).
- The full 1.56M-bar meta-labeler training (validated offline, not in the fast
  suite).
- End-to-end Telegram delivery (bot is exercised manually / via `/status`).

These are intentionally out of the green gate; see `RECOMMENDATIONS.md` P2 for
property-based and chaos tests to extend coverage.

---

## Adding a Test

1. Add a function `test_*` in the relevant `tests/test_*.py` (or a new module).
2. Keep assertions on *observable contracts* (shapes, constants, parity), not
   internal randomness.
3. Run `make test`; keep it green before committing.
