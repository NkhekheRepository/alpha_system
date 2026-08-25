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
