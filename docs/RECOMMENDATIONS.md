# Recommendations

**Scope.** Forward-looking, prioritized recommendations. Each item states the
action, the rationale, and the confidence (High/Medium/Low per OEOS evidence
policy).

---

## P0 — Must do before any capital claim

1. **Reach the pre-registered sample (G1: n≥100).** Live n=18, all TIMEOUT.
   Continue the demo run until a TP/SL + TIMEOUT mix exists. *Confidence: High.*
2. **Keep Alpha 3 simulation-only.** No real-capital path until H1 gates pass on
   live data. *Confidence: High.*
3. **Add a live-vs-synthetic divergence alert.** Flag when realized WR diverges
   beyond ±10 pp from the synthetic ledger. *Confidence: High.*

## P1 — Strengthen evidence

4. **Retrain the meta-labeler on real (not synthetic) resolved trades** once n≥100,
   then re-measure lift on live data. *Confidence: Medium* (depends on G1).
5. **Instrument TP/SL hit-rate live.** Currently ~0% (all TIMEOUT); confirm
   barriers are reachable at the live granularity before trusting the filter.
   *Confidence: High.*
6. **Add walk-forward persistence on live closed trades** (rolling 100-trade
   windows) to detect regime decay. *Confidence: Medium.*

## P2 — Engineering hardening

7. **Property-based tests for the triple-barrier engine** (random price paths →
   assert exactly one exit, correct PnL sign). *Confidence: High.*
8. **Chaos test: kill the runner mid-trade**, assert state reload resumes and
   `price_path` backfill resolves open positions. *Confidence: High.*
9. **Centralize the idx-boundary contract** in one shared constant to remove the
   199/200 divergence fragility. *Confidence: Medium.*
10. **CI gate:** run `make test` on every commit; block merge on red. *Confidence: High.*

## P3 — Research directions (only if P0/P1 clear)

11. **Cross-sectional / funding-rate ranking** as a genuinely novel intake family
    (W7 closed the single-threshold variant). *Confidence: Low.*
12. **Fractionally-differentiated features** with purged CV on the live stream.
    *Confidence: Low.*
13. **Cost-sensitive meta-labeler** optimizing for risk-adjusted return, not raw
    WR. *Confidence: Medium.*

---

*See `GOVERNANCE.md` for the deployment-block rules and `PHD_HYPOTHESIS.md` for the
gates these recommendations feed.*
