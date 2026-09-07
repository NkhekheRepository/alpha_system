# ADR-0001: Eliminate the Alpha 4 meta-labeler alias copy

- **Status:** Accepted
- **Date:** 2026-08-30
- **Decision:** Remove the alpha4 meta-labeler alias file (`models/meta_labeler_alpha4.joblib`) and have `alpha4_dry_runner.py` load the canonical `models/meta_labeler.joblib` directly, matching how `alpha3_dry_runner.py` already loads it.

## Context

Alpha 4% runs a meta-labeler gate (momentum signal filtered by `predict_proba >= 0.50`). The meta-labeler is trained by `scripts/train_meta_labeler.py`, which writes a single canonical model `models/meta_labeler.joblib` (git-tracked and committed).

Alpha 4's runner originally loaded a **separate copy** `models/meta_labeler_alpha4.joblib` (the "alias"), and `validate_meta_labeler()` SHA-compared the alias against the canonical, warning *"alias ... != canonical ... (stale copy after retrain)"* when they diverged.

**Observed problem:** after the 2026-08-29 18:17 retrain, nothing refreshed the alias, so the deployed alpha4 model was permanently stale (alias = 17:37 model, canonical = 18:17 model). The watchdog fired every startup and every `/audit` (`Alias == canonical: ❌ STALE`), producing persistent noise and leaving alpha4 running an older model. The watchdog correctly detected the desync, but the **refresh step was missing from the training workflow**, making this a recurring operational trap after every future retrain.

## Alternatives considered

1. **Keep the alias, make training refresh it** (write both canonical and alias in `train_meta_labeler.py`).
   - Preserves a "frozen alpha4 copy" that decouples alpha4 from alpha3 retrains.
   - **Rejected:** alpha4 does not have a distinct model — its feature order (36 features) and config (K=10, H=100, TP 3.5%, SL −2%, thr 0.50) are identical to the canonical model and to alpha3. A separate copy is pure duplication that must be manually kept in sync. It also leaves the *currently deployed* system stale until the next train is run.

2. **Eliminate the alias; load canonical directly (CHOSEN).**
   - Alpha 4's `FEATURE_ORDER` == alpha3's == the canonical model's stored features (verified, 36 features).
   - Alpha 4's config matches the canonical model's stored config exactly (verified).
   - Alpha 3 already loads the canonical directly with no alias machinery. Alpha 4 loading the same file changes nothing behaviorally.
   - Removes the entire class of desync/staleness bug permanently.

## Rationale

- Verified (not assumed): alpha4 `FEATURE_ORDER` == canonical stored features; config K/H/TP/SL in sync; model structure identical.
- Removes a redundant, unmanaged, git-untracked file (`meta_labeler_alpha4.joblib` was not in `git ls-files`) that was the sole source of a recurring stale-model warning.
- Matches the existing, proven alpha3 pattern.
- Simplifies `/audit` output (replace "Alias == canonical: ❌ STALE" with a positive "Model source: canonical meta_labeler.joblib ✅" line and record the canonical SHA).

## Trade-offs

- **Loss of a "frozen" independent copy:** If alpha4 ever needs a genuinely different model (different features, thresholds, or holdings-specific tuning), it will require a dedicated training path — the shared canonical is no longer a barrier to that, but a new model must then be trained explicitly for alpha4 rather than copied.
- **Retains the config/feature-order watchdog:** the fatal checks (feature-order mismatch, unreadable model) still hard-abort startup, so a silently-misaligned model remains impossible.

## Expected consequences

- Alpha 4 picks up the latest canonical retrain on next restart — no more running an 8-minute-stale model.
- `/audit` and startup logs no longer warn about alias/canonical divergence.
- Future retrains are automatically reflected in alpha4 (no manual copy step).
- A regression test (`tests/test_meta_labeler_alpha4.py`) guards that alpha4 points at the canonical file and loads without alias warning.

## Files changed

- `alpha4_dry_runner.py`: `META_LABELER_PATH` → canonical; removed alias-SHA check from `validate_meta_labeler` (replaced with canonical-SHA trace); removed unused `META_LABELER_BASE_PATH`; updated `meta_status()`/`meta_init` fields.
- `tg_bot_alpha4.py`: `/audit` + `_meta_audit_status` use `canonical_sha` and report "Model source: canonical".
- `models/meta_labeler_alpha4.joblib` / `.jobcp`: removed (moved to `dry_data/meta_labeler_alias_removed_20260830/`).
- `tests/test_meta_labeler_alpha4.py`: added (4 tests, all passing).
