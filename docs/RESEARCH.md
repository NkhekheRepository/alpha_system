# Research

**Scope.** This document narrates the *research content* of the Alpha program:
the questions asked, the AFML-conformant methodology, the synthetic-resolution
framework that makes Alpha 3 a proof instrument, the meta-labeler result, and the
limitations that keep the conclusion honest. Governance process lives in
`GOVERNANCE.md`; the formal hypothesis lives in `PHD_HYPOTHESIS.md`.

---

## 1. Research Questions

1. **RQ1 — Edge existence.** Does a tradeable momentum edge exist on the free
   Binance BTC/ETH 5m/1m surface?
2. **RQ2 — Exit machinery.** Can a triple-barrier exit (TP/SL/TIMEOUT) convert a
   signal into a bounded, bookable outcome?
3. **RQ3 — Meta-labeling.** Can a López de Prado secondary classifier filter a
   primary momentum signal to improve the tradeable hit-rate?
4. **RQ4 — Resolution.** What does a *bugged synthetic* resolution imply, and how
   does it differ from live markets?

---

## 2. Methodology (AFML-Conformant)

Following Marcos López de Prado, *Financial Machine Learning*:

- **Triple-barrier labeling.** Each signal is labeled by the *first* barrier
  touched (TP +2%, SL −2%, or vertical TIMEOUT at H=75), path-ordered — not a
  fixed-horizon return.
- **Purged K-fold cross-validation.** Train/test split uses a `PURGE` and
  `EMBARGO` gap ≥ the label horizon (75 bars) to prevent look-ahead leakage.
- **Feature-invariance test.** Features at bar *T* must not change when future
  bars are appended — the guard against the W6 full-window estimator leak.
- **Walk-forward persistence.** A config is accepted only if it persists across
  chronological folds (G1: ≥20 trades/fold; G2: positive net on ≥2/3 train folds).
- **Annualization derived from data.** Periods/year computed from actual mean
  trade duration, never a fixed constant.

---

## 3. The Synthetic-Resolution Framework (Alpha 3)

Alpha 3 is deliberately **not a market strategy**. It is a *controlled
demonstration* of what the bugged distribution implies:

- Same BTC/ETH momentum-K10 TP/SL 2% H75 engine as the live runner.
- Trade outcomes resolve **iid p=0.85 ±2%** with the W9 PnL formula
  (`pnl_dollars = 100000 * pnl_pct`).
- **Dual ledger:** each entry booked twice — once under real causal barriers
  (3% sizing, 0.1%/side fees) and once under the synthetic p=0.85 stream.
  Verified on BTC+ETH feathers: real WR 28.5% / net −$54,886 vs synthetic WR
  85.1% / net +$442,800 at 3%. The divergence *per trade* is the artifact.

Alpha 3 proves the machinery is correct; it does **not** prove edge, because every
real-data experiment on this surface is NO-GO.

---

## 4. Meta-Labeler Result (RQ3)

Pipeline (`scripts/`): fetch 1.56M bars → label 97,411 signals (53.3% raw WR) →
engineer 36 features → train RF with purged CV → validate walk-forward.

| Metric | Value |
|--------|-------|
| Out-of-fold AUC | 0.625 |
| Precision | 63.3% |
| OOS Filtered WR | 61.8% |
| OOS Raw WR | 52.9% |
| Lift | **+8.9 pp** |
| Selection rate | ~44% of primary signals |

The meta-labeler *works as designed*: it filters the primary stream toward
higher-probability winners on the distribution it was trained on.

---

## 5. Limitations (honest boundary)

1. **Synthetic-only validation.** The +8.9 pp is measured on Alpha 3's iid
   p=0.85 stream — a property of the synthetic generator, not of live markets.
   Per the Wave 9/10 lessons, *any* filter looks good on that distribution.
2. **Small live sample.** n=18 live demo trades, **all TIMEOUT** (no TP/SL hits
   yet). Machinery validated; live edge UNKNOWN.
3. **Barriers decorative at this scale.** ~96% of exits are TIMEOUT, so the
   meta-labeler's value-add (entry timing into TP/SL) is not yet observable live.
4. **No real capital.** Alpha 3 is simulation/paper by design; the result must
   not be extrapolated to deployment.

---

## 6. References

- López de Prado, M. (2018). *Financial Machine Learning*. Wiley.
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. CUP.
- OWASP ASVS / NIST SSDF — security and supply-chain hygiene.
- OEOS engineering spec (`~/.config/opencode/AGENTS.md`) — governance, evidence
  policy, OEOS lessons Wave 6–10.
- Companion: `GOVERNANCE.md`, `PHD_HYPOTHESIS.md`, `HEDGE_REPORT.md`.
