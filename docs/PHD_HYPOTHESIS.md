# PhD Hypothesis

**Scope.** This document states the doctoral-level thesis and a single,
testable sub-hypothesis with its pre-registered success gates. It is the formal
hypothesis layer above `RESEARCH.md` (method) and `GOVERNANCE.md` (process). The
sub-hypothesis is the live, falsifiable claim; the thesis frames the broader
contribution.

---

## 1. Thesis

> **Thesis.** *Secondary machine-learning meta-labeling improves the
> tradeable hit-rate of a primary momentum signal on crypto 1-minute data —
> but only when the meta-labeler is trained and validated on the same
> resolution-class and event-frequency as live execution, and only after the
> live execution machinery is independently verified correct. Absent these
> conditions, a positive backtest is an artifact of synthetic resolution or
> leakage, not market edge.*

The thesis is supported by the program's 13-wave ledger: every real-data wave is
NO-GO, while every bugged-synthetic wave trivially passes — demonstrating that
*meta-labeling correctness and execution correctness are necessary precursors to
any edge claim*.

---

## 2. Testable Sub-Hypothesis (H1)

> **H1.** On the Alpha 3 live demo-fapi book, a Random-Forest meta-labeler
> (P(win) ≥ 0.50 threshold) applied to a momentum-K10 primary signal raises the
> **realized** win-rate and risk-adjusted return above the unfiltered primary
> signal, within a pre-registered observation window.

> **H0.** The meta-labeler produces no improvement over the unfiltered primary
> signal on realized live metrics (difference in WR and Sharpe within noise).

---

## 3. Pre-Registered Success Gates

These gates are declared *before* live evaluation. The experiment concludes when
**any** terminal gate is met.

| Gate | Condition | Pass criterion |
|------|-----------|----------------|
| G1 — Sample | Enough events to decide | ≥ 100 closed trades with a TP/SL+TIMEOUT mix |
| G2 — Machinery | Engine books correctly | 100% of exits reconcile to PnL sign; equity matches state |
| G3 — Edge (primary) | Unfiltered signal works | WR ≥ 50% and net > 0 on ≥ 2/3 of thirds |
| G4 — Edge (filtered) | Meta-labeler adds value | Filtered WR > Raw WR by ≥ 5 pp (live), p < 0.05 |
| G5 — Risk | Bounded downside | MaxDD ≤ 25% at realized sizing; no 100% liquidation path |
| G6 — Frequency | Tradeable event stream | ≥ 1 entry per 500 polls (not merely significant regression) |

**Decision rule.**
- G1 ∧ G2 ∧ G3 ∧ G4 ∧ G5 ∧ G6 → **ACCEPT H1** (live edge, still simulation-only).
- G1 ∧ G2 ∧ ¬G3 (or ¬G4) → **REJECT H1** (no live edge; machinery sound).
- ¬G2 → **INVALID** (machinery bug; fix and re-run, do not score).
- ¬G6 → **REJECT on frequency** (significant association ≠ tradeable stream).

---

## 4. Threats to Validity

| Threat | Mitigation |
|--------|------------|
| Synthetic distribution leakage | Dual-ledger; never train on bugged stream |
| Look-ahead in features | Feature-invariance test; purged CV |
| Small-sample noise | G1 minimum n=100; report CIs |
| Regime shift | Walk-forward folds; embargo |
| Machinery mis-booking | G2 reconciliation before scoring |
| Multiple testing | Single pre-registered H1; intake gate on variants |

---

## 5. Expected Contribution

- A reproducible AFML-conformant meta-labeling pipeline that *fails honestly* on
  a no-edge surface (the real-data NO-GO) and *passes diagnostically* on a
  synthetic surface (proving the engine, not the edge).
- A documented discipline for separating *machinery correctness* from *market
  edge* — the central lesson of the program.
- Empirical evidence (live) on whether meta-labeling converts a no-edge primary
  signal into a tradeable one at 1-minute resolution.

---

## 6. Status

- **Training/validation (synthetic):** H1-supporting (+8.9 pp OOS). This measures
  the engine, not live markets.
- **Live evaluation:** in progress; G1 not yet met (n=18, all TIMEOUT). Edge
  UNKNOWN. Machinery G2: PASS.
