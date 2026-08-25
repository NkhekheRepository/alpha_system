# Governance

**Scope.** This document records the governance discipline, the experimental
ledger, and the deployment-block rules that govern the Alpha system. It is the
"how we decide" counterpart to `RESEARCH.md` (the "what we found"). Governance
findings are kept separate from research findings to avoid duplicating the
13-wave evidence while still being auditable.

---

## 1. Governance Principles

The system is operated under the OEOS engineering specification (see
`~/.config/opencode/AGENTS.md`), which mandates:

1. **Pre-registration.** Every experiment declares its hypothesis, parameter grid,
   success gates, and analysis plan *before* any data is touched.
2. **Evidence over assertion.** A result is accepted only when *run*, not when
   asserted. Tests, linters, and backtests are executed; outputs are captured.
3. **Gate on frequency, not association.** A signal is tradeable only if it
   produces enough *events in the implementation* — not merely a significant
   regression coefficient.
4. **Self-certification is not evidence.** Deployment is gated on execution
   evidence and out-of-sample data, never on in-repo "CERTIFIED" documents.
5. **Block on confirmed P0.** Any confirmed show-stopper blocks deployment
   regardless of score.

---

## 2. Experimental Ledger (13 Waves)

Every real-market wave on the free Binance surface is **NO-GO**. The table is the
program's verified answer; the AFML-conformant null is materially stronger
evidence than the prior leaky pipelines.

| Wave | Question | Method | Result | Verdict |
|------|----------|--------|--------|---------|
| ADR-0001 | Factor A | Pre-reg | — | NULL |
| ADR-0002 | Factor B | Pre-reg | — | NULL |
| ADR-0003 | Sampling × fracdiff | Purged CV | cand 0.054 vs base 4.696, perm_p 0.0033 | NO_GO |
| W6 | Momentum (free surface) | AFML IS + fracdiff | net≈0, 112/117k trades | NO_GO |
| W7 | Funding-rate mean-reversion | Pre-reg thresholds | n=3 trades / 7 mo | NO_GO |
| W8-1 | Momentum grid (720) | Fixed-barrier BT | 0/720 pass | NO_GO |
| W8-2 | Vol-scaled barriers | Fixed-barrier BT | — | NO_GO |
| W8-3 | Momentum (432) | Fixed-barrier BT | 0/432 pass | NO_GO |
| W8-4 | Momentum (432) | Fixed-barrier BT | 0/432 pass | NO_GO |
| Deep (5m) | Momentum K10 | Full-window causal BT | −$55,181, WR 29.6%, Sharpe −31 | NO_GO |
| Walk-forward (real) | 108 configs × 4 folds | Purged WF | 0/108 G1+G2 | NO_GO |
| 1m live-granularity | 18 configs | Causal 1m WF | 0/18 G1+G2 | NO_GO |
| Walk-forward (bugged synthetic) | 108 configs | Purged WF | 108/108 PASS | Diagnostic only |
| Meta-labeler (Alpha 3 synthetic) | RF secondary filter | Purged CV + OOS | Filtered 61.8% vs Raw 52.9% | +8.9pp (synthetic) |

**Interpretation.** Across 1,600+ parameterizations the momentum family shows **no
edge** on BTC/ETH 5m/1m at any scale. The bugged-synthetic walk produces trivial
PASSes — proof the selection artifact is in shared code, not a unique strategy.

---

## 3. Pre-Registration Discipline

- Registration hash (`sha256`) makes each protocol auditable; the grid is frozen
  *before* any run.
- A rejected hypothesis family is **closed**; a renamed/rescaled variant is
  rejected at intake (W6 lesson: intake is the only reopen gate).
- Re-running a closed grid is forbidden; the correct fix for a defective run is
  `git restore` of governance files + clean re-registration, never a re-run or
  manual counter edit.

---

## 4. Deployment-Block Rules

| Condition | Action |
|-----------|--------|
| Confirmed P0 (e.g. `stoploss=-0.99` at 30x, ruin prob 1.0) | BLOCK deploy |
| Live runner shows 0 trades while "running" | Inspect exit path, not the market |
| Leverage applied to 100%-notional bug | BLOCK (instant ruin) |
| Synthetic +8.9pp presented as live edge | Reject claim; edge UNKNOWN |

Alpha 3 is permitted to run **only** because it is simulation/paper (zero real
capital). It is **never** authorized for real-capital deployment.

---

## 5. OEOS Lessons (condensed)

- **Wave 6 — Permutation contamination:** test covariance, not raw mean return;
  demean forward returns first.
- **Wave 6 — Baselines must be causal:** a leaky baseline inflates the bar.
- **Wave 6 — Annualization must be data-derived:** fixed constants → absurd Sharpe.
- **Wave 7 — Significance ≠ tradeable event:** gate on event *frequency*.
- **Wave 8 — Fixed % barriers are decorative** at 5m/1m (≈0.5% hit rate); exits are
  ~96% TIMEOUT.
- **Wave 8 — Fixing exits does not create edge:** diagnose signal and exits separately.
- **Wave 9 — Synthetic-backtest trap:** `pnl_dollars = 100000 * pnl_pct` inflates
  results identically for every strategy; always verify position scaling.
- **Wave 10 — Leverage amplifies existing PnL:** no edge × leverage = faster ruin;
  100% MaxDD inevitable without edge.
- **Wave 10 — Live machinery must be correct before judging edge:** the first trade
  in system history was booked only after the triple-barrier fix.

---

## 6. Current Status & Open Items

- **Live:** Alpha 1, Alpha 2 (paper), Alpha 3 (demo hedge) running; meta-labeler
  deployed; 27 automated tests passing.
- **Edge:** UNKNOWN on live data (n small, all TIMEOUT exits). Machinery: PASS.
- **Open:** reach n≥100 with a TIMEOUT/TP-SL split before any capital claim;
  retrain meta-labeler on *real* data if a live edge is ever hypothesized.
