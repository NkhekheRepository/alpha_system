# SWOT Analysis

**Scope.** Strategic assessment of the Alpha 3 demo system as of this build.
Internal factors (Strengths/Weaknesses) are verified from the codebase and live
state; external factors (Opportunities/Threats) are judgment calls labeled with
confidence.

---

## Strengths
- **Honest machinery.** Triple-barrier exit, PnL-by-sign bookkeeping, and
  effective-equity tracking are verified correct (Wave 10 fix; tests green).
- **Governed discipline.** Pre-registration, purged CV, walk-forward persistence,
  evidence-over-assertion — rare in retail quant work.
- **Reproducible artifacts.** Frozen model + metrics committed; `deploy.sh`
  redeploys in a few steps; `generate_hedge_report.py` regenerates the report.
- **Zero capital at risk.** Demo-fapi paper hedge; no real-money exposure.
- **Test coverage.** 27 tests encode parity contracts across config, features,
  labels, equity, demo-trader, runner helpers.

## Weaknesses
- **No live edge demonstrated.** n=18, all TIMEOUT; edge UNKNOWN. Real-data waves
  are uniformly NO-GO.
- **Synthetic-only validation.** The +8.9 pp meta-labeler lift is measured on the
  iid p=0.85 stream — a property of the generator, not live markets.
- **Decorative barriers at scale.** ~96% TIMEOUT exits mean the filter's
  value-add (entry timing into TP/SL) is not yet observable.
- **Small sample / high variance.** CIs on live metrics are wide; G1 not met.

## Opportunities
- **Live data as the final arbiter.** Reaching n≥100 with a TP/SL mix could
  falsify or support H1 on real data (Medium confidence).
- **Disciplined platform reuse.** The AFML pipeline + governance can be pointed at
  genuinely novel intake families (cross-sectional funding ranking) without
  re-deriving process (Low–Medium).
- **Educational value.** The honest null ledger is a strong teaching artifact for
  quant-risk literacy (Medium).

## Threats
- **Over-generalizing the synthetic lift.** Risk that +8.9 pp is mistaken for live
  edge (High likelihood if undisciplined; mitigated by GOVERNANCE gates).
- **Regime shift.** Crypto microstructure can change; a passed H1 may not persist
  (Medium).
- **Operational fragility.** idx-boundary divergence and state-reload edge cases
  could mis-book if not hardened (Medium; mitigated by P2 tests).
- **Exchange/symbol changes.** Demo-fapi symbol delisting or LOT_SIZE changes
  break `round_qty` (Low–Medium).

---

*Confidence labels per OEOS: High = verified in code/live state; Medium = inferred
with supporting evidence; Low = speculative. See `GOVERNANCE.md`, `RESEARCH.md`.*
