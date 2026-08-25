# Story — From 84% Win Rate to an Honest Machine

*Where we started, what we learned, and where we are today.*

---

## Prologue: The Seductive Number

It began with a beautiful result. A backtest printed **+84% win rate, +$72,000,
Sharpe 16**. Two strategies — Alpha 1 (long-only) and Alpha 2 (bidirectional) —
both passed. A "Deep" configuration was selected. The numbers said: ship it.

They were lies. Not malicious lies — structural ones. A single line of code,
`pnl_dollars = 100000.0 * pnl_pct`, had sized every trade at **100% of capital**
instead of the stated 3%. The synthetic 50-trade walk that produced the triumph
was, mathematically, a money printer by construction. Identical for both
strategies. The selection artifact lived in shared code, not in any edge.

That is how the journey began: with a result we wanted to believe.

---

## Act I: The Audit

Before any capital moved, an institutional-grade forensic audit (the Phoenix
Scalper audit, codified in our OEOS lessons) tore the codebase open. The findings
were a checklist of how *not* to build a quant system:

- Full-window estimator fit — state at time *T* depended on data *after* T.
- Labels that did not match the real exit policy.
- No purge, no embargo, no uniqueness — random splits of dependent 5-minute trades.
- Multiple testing without governance — 13 strategy generations, 208 backtests.
- Self-certification: a "10.0/10 CERTIFIED FOR PRODUCTION" doc, edited fixtures to
  pass, deployed anyway. Seven bots, all losing.
- Ruin-level risk shipped: `stoploss = -0.99` at 30x, Monte-Carlo ruin probability 1.0.

The audit taught the first law of this program: **a running bot with zero trades
is a red flag — inspect the exit path, not the market.**

---

## Act II: The Thirteen Nulls

We stopped chasing backtests and started pre-registering experiments. Wave after
wave, the free Binance surface answered the same way:

- W6 — AFML-conformant search: candidate 0.054 vs baseline 4.696, `perm_p 0.0033`
  → **NO_GO**.
- W7 — Funding-rate mean-reversion: a t-stat of −31.8 (the strongest association
  ever) produced **3 trades in 7 months**. Significance is not a tradeable stream.
- W8 — 1,605+ momentum parameterizations across four experiments: **0 passed**.
  Fixed ±2% barriers were decorative (0.5% hit rate; 96% TIMEOUT).
- Deep (5m) full-window: **−$55,181, 29.6% WR, Sharpe −31**.
- Walk-forward (real, 108 configs × 4 folds): **0/108**.
- 1m live-granularity validation: **0/18**.

Thirteen waves, every real one NO-GO. The bugged-synthetic arm, run on the *same*
grid and gates, passed 108/108 — proving the artifact was in the code, not the
strategy. The null became our most valuable evidence.

---

## Act III: Saving the Machine

The audit found the live runners were **dead**. `price_history` froze at entry; the
vertical barrier was ignored; SL PnL was negated; the shared short logic was
inverted. Both bots appeared "running" with flat equity and zero trades for two
days. The smoking gun: BTC crossed its +2% TP at live price — and nothing was
recorded.

We fixed the machinery: runner-side exit evaluation, a per-position live price
path, correct TIMEOUT handling, PnL by sign. Within twelve minutes the first trade
in system history booked: Alpha 1 BTC TP at exactly +2% → +$60.00, not a cent off.
Four trades later: 4W/0L, +$178.59, 100% WR. The honesty clause is carved in:
**four trades validate the machinery, not the edge.** The causal backtest still
says long-run negative. But now the system emits real evidence every cycle.

---

## Act IV: Alpha 3 — A Honest Demonstration

Alpha 3 is the synthesis. Same momentum engine, but a **meta-labeler** — a López de
Prado secondary classifier — gates the primary signal: enter only when P(win) ≥
0.50. Trained on 1.56M bars with purged cross-validation, it lifts the validated
win-rate from 52.9% to 61.8% (**+8.9 pp**). The out-of-fold AUC is 0.625.

But Alpha 3 is **simulation-only by design**. It places *paper* hedge orders on
Binance demo-fapi (zero real capital) and resolves its synthetic stream iid
p=0.85. The dual ledger — real barriers vs synthetic — proves the engine; it does
not claim edge. Live, it has booked 18 trades, all TIMEOUT, machinery correct,
edge UNKNOWN. It runs, it is honest, it is deployable in a few steps, and it will
never touch real money until the pre-registered gates say otherwise.

---

## Epilogue: The Lesson for the World

We set out to build a trading system and we built something more useful: a
**discipline**. The market did not give us an edge. It gave us the humility to
build a machine that tells the truth — that separates machinery from edge, that
fails loudly and honestly, that treats a beautiful number as a hypothesis to
destroy, not a trophy to ship.

The 84% win rate was a bug wearing a victory medal. The real win was learning to
say, with evidence, *we do not have an edge yet — and here is exactly why.* That
is the system we run today.

---

*This story is told in code and evidence in `ARCHITECTURE.md`, `RESEARCH.md`,
`GOVERNANCE.md`, `PHD_HYPOTHESIS.md`, and `HEDGE_REPORT.md`.*
