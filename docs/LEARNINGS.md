# Learnings

**Scope.** Consolidated engineering and quantitative lessons from the Alpha
program. These are the durable takeaways that should shape any future work. The
full OEOS lesson log lives in `~/.config/opencode/AGENTS.md`; this is the condensed
operational set.

---

## Engineering Lessons

1. **A running bot with 0 trades is a red flag.** Inspect the exit path, not the
   market. Both live runners showed flat equity for two days — dead exit code, not
   low event frequency.
2. **Machinery precedes edge.** A +2% TP crossing with zero recorded trades is a
   bug, never a market condition. Fix and verify the engine before judging signal.
3. **Single source of truth for config.** Every component imports `ALPHA3_ASSETS`
   and API base from `binance_config.py`; no hard-coded symbol lists.
4. **Tests are a gate, not a formality.** 27 automated tests encode the parity
   contracts (config, meta-labeler, features, labels, equity, demo-trader, runner
   helpers) and must stay green on every change.
5. **Version every change.** `git` tracks all source, docs, model, and metrics;
   runtime state and backups are untracked by design.

## Quant Lessons

6. **Significance ≠ tradeable event.** A t-stat of −31.8 produced 3 trades in 7
   months. Gate on event *frequency in the implementation*.
7. **Synthetic-backtest trap.** `pnl_dollars = 100000 * pnl_pct` inflates results
   identically for every strategy. Always verify position scaling.
8. **Fixed % barriers are decorative** at 5m/1m (≈0.5% hit rate; ~96% TIMEOUT).
   Diagnose exits and signal separately.
9. **Leverage amplifies existing PnL.** No edge × leverage = faster ruin; 100% MaxDD
   inevitable. Never apply leverage to a strategy with the 100%-notional bug.
10. **Walk-forward persistence closes the question.** 0/108 configs passed G1+G2;
    without the persistence gate, the best in-sample rank would have been a
    selection artifact.
11. **Kelly on real data says bet 0; on the bugged number says 35x.** The bugged
    distribution makes *any* sizing look like a money printer.
12. **Baselines and annualization must be causal and data-derived.** Leaky/constant
    baselines inflate the bar and produce absurd Sharpe.
13. **Self-certification is not evidence.** Deployment gates on execution evidence
    and OOS data, never in-repo "CERTIFIED" docs. Block on confirmed P0.

## 48-Asset Expansion Lessons (2026-09-12)

14. **Latency optimization is state-level, not code-level.** The 5s `/status`
    latency was caused by 200 full depth snapshots per symbol (multi-MB state
    bloat) × Telegram JSON serialization. Capping `ob_history` at 25 (model
    uses only 36 OHLCV features at `FEATURE_ORDER[:36]`) cut state size 8× and
    `/status` to <0.4s. Always profile state reads, not just compute.
15. **State-derived prices beat API calls for display.** `state_prices(state)`
    reads the last close from in-state `price_history` (≤1 runner cycle stale,
    display-only) — avoids a ~1.3s testnet round-trip on the `/status` critical
    path. Fallback to `get_prices()` only when history is empty (fresh boot).
16. **conftest TESTNET_LIVE=False is load-bearing.** Tests mock `DEMO_LIVE=False`
    but `TESTNET_LIVE=True` (from `.env` dev keys) still fires real testnet
    orders for fake symbols. Global mock in `conftest.py` prevents all exchange
    calls in test — no test may ever touch any exchange.
17. **Threshold 0.61 is precision over frequency.** 33-asset sweep showed
    +0.156%/trade in-sample at 0.61; live flow is ~p99.9+ (trade every few
    hours). 0.57 was breakeven; 0.61 trades less often but with tighter
    precision. User chose precision; this is a conscious tradeoff, not a bug.
18. **48-asset retrain on 3GB box needs memory discipline.** `MALLOC_ARENA_MAX=2`,
    `n_jobs=1`, stop runner before training (3GB RSS at peak). The 854k-sample
    48-asset dataset takes ~40min for 5-fold purged CV + final fit. First
    OOM-kill was from running features + runner simultaneously.

## A2 Half-Kelly Sizing Deploy (2026-09-14)

23. **The deployed 4.0x was near-full-Kelly — optimal only on paper.** Kelly on
    the 36-trade R-distribution (p=0.444, payoff 1.50R) gives f*=4.64x notional;
    the running 0.20x20=4.0x was essentially full-Kelly sizing on an n=36
    distribution whose WR CI (27-58%) spans breakeven. Full Kelly + uncertain
    edge = 47% realized DD. Half-Kelly (2.32x, deployed as 0.12x20=2.4x) keeps
    ~80% of the return (+11.1% vs +13.9% replay) for ~65% of the drawdown
    (28.5% vs 43.7%) and cuts 100-trade P(DD>50%) from 50% to ~10%.
24. **The installed systemd unit is a copy, not a symlink.** Editing
    `systemd/alpha3-dry-runner.service` and restarting changes nothing — the
    running unit is `~/.config/systemd/user/alpha3-dry-runner.service`
    (installed Sep 10 by `deploy.sh cp`). The first restart silently ran the
    OLD `--stake 0.20` (verified via `systemctl show -p ExecStart`). Deploy
    rule: cp + daemon-reload + restart, then verify `ExecStart` + migrate log
    + persisted `stake_pct` before declaring done.
25. **Stake migration is safe but lazy.** `load_state` migrates stake/lev
    in-memory (`stake 0.2->0.12, preserving DB 36t/$11.28`) while the old
    process's shutdown save briefly re-persists old values; the file converges
    on the new process's first full cycle save. Verify     the *file*, not just
    the log line — and expect a multi-minute lag (48-asset bootstrap).

## Testnet recvWindow Timestamp Fix (2026-09-13)

19. **Testnet and demo-fapi are different servers with different clocks.**
    `sync_binance_time()` synced against `demo-fapi.binance.com`, but testnet
    orders go to `testnet.binancefuture.com`. The cached offset from one server
    does NOT apply to the other — causing intermittent `recvWindow` timestamp
    errors on testnet leverage set and live close. Fix: separate
    `sync_testnet_time()` + `server_timestamp_testnet()` with its own offset.
20. **Server time sync must be periodic, not one-shot.** The original
    `sync_binance_time()` synced once at startup and cached forever. Over hours
    of runtime, even small clock drift accumulates past the recvWindow. Fix:
    re-sync every 30 minutes inside `server_timestamp()`.
21. **`_signed_get` in the runner was a hidden timestamp bug.** The reconcile
    and orphan sweep use `_signed_get('/fapi/v2/positionRisk')` which had its
    own raw `time.time()` + `recvWindow=10000` — completely independent of the
    centralized `sign_query` path. If this fails, the sweep can't even detect
    orphans. Fix: `_signed_get` now uses `server_timestamp_testnet()` + 50s
    recvWindow, same as the order path.
22. **Orphan positions survive a failed close.** Paper position was closed
    locally (SL booked), but both demo and testnet exchange legs were stranded.
    The periodic orphan sweep (`cycle % 60`) retries every ~10 minutes — but
    only if `_signed_get` works. The VTHOUSDT orphan (SHORT 67689) was closed
    on the next restart after the timestamp fix was deployed.
