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
