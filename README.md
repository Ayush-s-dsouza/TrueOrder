# TrueOrder

A debt-repayment sequencing engine for a mixed Indian debt portfolio (credit
cards, personal/home/auto/education loans) that computes a tax-and-fee-
adjusted repayment order alongside the naive avalanche order most tools and
AI assistants give today, and shows exactly where, why, and how reliably
they diverge.

## The gap

Asked directly -- "I have 5 EMIs and 4 credit cards, what order should I
repay them in?" -- Dhruva returns textbook avalanche: sort by stated
interest rate, highest first. No question about tax regime, no question
about whether a property is self-occupied or rented out, no mention that a
floating-rate loan and a fixed-rate loan of the same stated APR carry very
different prepayment consequences. Checking independently: the in-app
Cards/Loans tabs are per-instrument only, and Oolka's premium tier is
utilisation alerts and bureau-dispute automation -- genuinely useful, but
not avalanche/snowball optimization or lump-sum-split guidance across a
portfolio. Naive avalanche isn't wrong in general -- for an all-unsecured
portfolio with no tax-advantaged debt, it's the right answer, and this
project's own "agreement case" sample confirms the two orderings converge
exactly when nothing distinguishes them. It's wrong specifically in the
cases that produce a genuine conflict, and those are what the rest of this
README is about. See [RUNBOOK.md](RUNBOOK.md) for the full manual process
this replaces, step by step.

## The core finding

A single "optimal" repayment order is a category error. Asking "what order
should I repay my debts in?" is actually asking about three separate,
sometimes-conflicting objectives at once, and collapsing them into one
"cheaper" or "optimal" label -- the way naive avalanche does implicitly, and
the way this project's own adjusted order could just as easily have done if
built less carefully -- misrepresents what kind of claim is being made for
at least one of the three:

- **Tax** -- a verified deduction lowers a debt's true cost. A rupee claim,
  and (usually) a reliable one.
- **Fee** -- a verified foreclosure charge raises a debt's true cost above
  its stated rate. Also a rupee claim, but never a savings guarantee --
  more on why below.
- **Utilisation** -- a heuristic that protects a credit score, not rupees.
  Explicitly *not* a rupee claim at all; promoting a card for this reason
  can cost a little real money as the price of the trade, on purpose.

That much would already justify keeping the three mechanisms separate
(`schema.DivergenceMechanism`, `DivergenceRationale`, enforced by a
validator that makes `traded_for` required for utilisation and forbidden
for tax/fee -- see DECISIONS.md). But there's a second, deeper layer,
found only by actually simulating outcomes rather than trusting the
ranking that produced them: **two of the three mechanisms are further
unstable across time, because they are ranked from a single point-in-time
snapshot of what is actually a path-dependent process.**
`sequence.py` computes each debt's true cost once, before any
month-by-month simulation exists to walk forward in time. That snapshot is
a faithful stand-in for a debt's whole repayment life only when its true
cost per rupee stays constant throughout -- and for fee and (part of) tax,
it doesn't:

- A foreclosure charge is a one-time lump sum tied to whatever balance
  happens to remain at the exact moment of payoff, not a cost that accrues
  continuously the way interest does. Annualizing it into a rate for
  ranking purposes compares a lump sum against an ongoing cost as if they
  were the same kind of quantity -- so prioritizing the "more expensive"
  debt by that ranking does not reliably reduce the real, simulated total.
- A home loan whose interest exceeds rental income plus the Section
  71(3A) ₹2,00,000 cap has a deduction that is a *fixed rupee amount*. As
  the balance amortizes down and annual interest shrinks, that fixed cap
  becomes a *larger fraction* of a *smaller* interest bill -- the tax
  shield genuinely improves over the loan's life instead of holding flat.
  A snapshot taken once, before any of that amortization has happened,
  cannot see the improvement coming.

Both failures are the same root cause wearing two mechanisms' clothing, not
two unrelated quirks (see DECISIONS.md's "one root cause, not two" entry).
Verified directly, not assumed: sweeping this project's own eval manifest
for the affected tax segment shows three portfolios where the adjusted
order comes out cheaper and three where it comes out very slightly more
expensive -- same mechanism, same attribution logic, opposite outcome,
depending only on where each portfolio happens to sit in its amortization.

## Worked example: the same mechanism, the same segment, opposite outcomes

Both of the following are real, unedited `explain()` outputs for the exact
same segment (`letout_home_old_regime_loss_capped` -- an old-regime,
let-out home loan whose interest exceeds the Section 71(3A) cap) --
different portfolios, same divergence, same tax mechanism correctly
identified and correctly reasoned about in both. The only thing that
differs is where each portfolio's numbers land relative to the cap, which
`sequence.py`'s upfront ranking has no way to know.

**Instance where it works as the ranking implies** (`samples/sample_007_letout_home_old_regime_loss_capped.json`, net_cost_delta = +Rs 7,762.54):

> If you just rank everything by the headline APR on your statements, you
> would attack your credit card (cc1) first at 42 percent, then your home
> loan (h1) at 11 percent, then your personal loan (pl1) at 10.5 percent;
> that naive order is cc1, h1, pl1. But the engine factors in tax and fees
> to find the true effective cost, and it returns cc1, pl1, h1. [...] You
> are on the old regime with a let-out property, and the interest is
> giving you a deduction of Rs 300,000 this year, which is worth Rs 90,000
> per year at your 30 percent marginal rate. [...] When you run the
> simulation with the surplus you were given, the adjusted order comes out
> cheaper in practice. The simulated net cost difference is Rs
> 7,762.54 -- meaning naive minus adjusted -- so following the adjusted
> order saves you about that much in real cost over the life of the plan.

**Instance where it doesn't** (`letout_home_old_regime_loss_capped_002` from the eval manifest, net_cost_delta = -Rs 1,417.93):

> Your home loan (h1) is a let-out property claimed under the old tax
> regime, and it carries a genuine, reliable tax saving of Rs 90,000 per
> year through Section 24(b): the interest is fully deductible against
> rental income with no cap, plus you can set off up to Rs 200,000 of the
> resulting loss against other income under Section 71(3A), giving a
> deductible amount of Rs 300,000 this year. That tax benefit pulls h1's
> true cost below its stated rate, which is why the adjusted plan pushes
> it to the back and clears pl1 first. [...] If you follow the adjusted
> order instead of the naive one with the same monthly surplus, it costs
> slightly more in practice: the simulated net cost is Rs 4,174,519.51
> compared with Rs 4,173,101.58, a difference of Rs 1,417.93 over the full
> 116-month payoff period.

Both explanations pass every check in `eval/metrics.py` -- they are two of
the 58/58 baseline and 26/26 held-out calls that did. Neither one is
wrong; the second is simply honest about an unfavorable number instead of
assuming the mechanism's usual reliability applies here too. That honesty
is the entire point --
`explain.py`'s system prompt requires stating the real simulated
comparison exactly as computed, never inferring it from which mechanism
fired.

## Eval results

Ground truth is generated by this project's own deterministic core --
`eval/manifest.py` builds 42 cases across all 7 named segments (6 each);
`eval/collect.py` calls `explain()` per case; `eval/metrics.py` grades each
explanation against what `sequence.py`/`impact.py` actually computed for
that exact portfolio.

**Baseline (`tune`+`validation`, 2 repeats/case, 0 errors, Rs 40.85 total
cost): 100% faithfulness (58/58 calls).** Not the first number produced --
the first full run scored 79.3% (46/58 calls), and every apparent
"failure" behind that number turned out, on inspection, to be a bug in
the grading heuristic,
not in `explain.py`'s output. Five of them in total: a number-matching
check that was sign-sensitive (a correctly restated "costs Rs 949.66 more"
flagged as fabricating a number that appeared in the ground truth as
-949.66), a false-claim detector with no negation handling ("there are no
tax deductions" flagged as claiming one), an order-check that silently
verified the *naive* sequence instead of the adjusted one (naive is
conventionally described first in prose), an admission-phrase pattern
broken by punctuation in rupee figures, and a fabrication check that
couldn't recognize correct arithmetic on given numbers. Each is a
permanent regression test in `tests/test_eval_metrics.py` now, with the
literal real-world string that exposed it.

**Held-out `test` split (2 repeats/case, opened once via
`load_split('test', allow_test=True)`, logged in
`eval/TEST_SET_ACCESS_LOG.jsonl`, 0 errors, Rs 17.63 total cost): 100%
faithfulness (26/26 calls).** Also not the first number: the first pass
scored 96.2% (25/26 calls), and the one failure was investigated with the
same discipline as the baseline run rather than accepted as-is -- a
genuinely favorable,
correctly-reasoned outcome ("the adjusted sequence costs you less
overall", `net_cost_delta = +Rs 3,552.60`) was missed because
`SAVINGS_LANGUAGE_PATTERN` recognized "save"/"cheaper"/"lower cost" but
not "costs ... less", the exact mirror-image gap already fixed on the
*costlier*-admission side earlier in this same eval's development and not
generalized to its opposite at the time. Sixth metrics bug found this way,
sixth permanent regression test. The held-out split's actual job --
confirming the baseline result generalizes to data never previously
inspected, since no prompt tuning happened in between (`eval/
experiments.py` was never built, see below) -- is what this second 100%
(26/26 calls) result demonstrates.

## Remaining limitations

- **`marginal_tax_rate_pct` is a required input, not derived from income.**
  Computing India's actual slab/surcharge/cess schedule (which changes most
  Finance Acts) is a real verification burden orthogonal to this project's
  actual value -- debt-repayment sequencing, not tax-slab calculation. The
  caller states their own bracket directly; getting this wrong is on the
  input, not on `tax_rules.py`.
- **The utilisation/CIBIL heuristic's score-impact range is explicitly a
  heuristic, not a calibrated figure.** The 30% aggregate-utilisation
  threshold itself is real and widely cited; the commonly quoted "30-80
  point" score impact is not published by any bureau.
  `utilisation_priority_score` is a binary crossing signal for exactly
  this reason, and `DivergenceRationale.traded_for` states the uncertainty
  explicitly whenever the mechanism fires.
- **Single-point-in-time ranking is now a stated, proven limitation, not
  an unexamined assumption.** This is the core finding above, restated as
  a limitation rather than a discovery: `sequence.py` cannot see a debt's
  cost trajectory, only its cost right now, and for a rupee cap or a
  one-time charge, "right now" is not the whole story. Extending the
  ranking to integrate true cost over a debt's projected path instead of
  sampling it once is the natural next step, and is explicitly out of
  scope for this build.
- **Synthetic amounts throughout.** Every sample and eval portfolio is
  generated by `synth/generator.py`, chosen to reliably trigger a specific
  divergence, not fit to any real population.
- **Tax and fee rules are current as of 2026-09-06** (every rule in
  `tax_rules.py`/`fee_rules.py` cites its source) and are subject to
  change by a future Finance Act or RBI circular.
- **Five debt types, chosen for dimension coverage, not exhaustiveness.**
  Gold loans, loan-against-securities/mutual-funds, BNPL/short-term app
  loans, and overdraft facilities are explicitly out of scope.
- **No compound divergence support yet.** A hypothetical fixed-rate,
  let-out home loan (both tax and fee mechanisms active on the same debt
  at once) is deliberately unsupported -- proven to raise through the real
  pipeline, not just at the type level, in `tests/test_sequence.py`.
- **`eval/experiments.py` (prompt-hypothesis tuning) was not built** --
  there is nothing to tune against a 100% (58/58 calls) baseline, and it
  was already the
  first item in this project's own cut order.
- **No persistence/CLI layer.** `emit.py`/`audit.py`/`pipeline.py`/`run.py`
  from the original design are not implemented; `demo_checkpoint.py`,
  `api.py`, and the `eval/` scripts are the only ways to run this today.

## What it does

Five deterministic stages, zero LLM calls, enforced by an AST-based test
(`tests/test_no_llm_imports.py`) that would fail if any of them ever
imported one -- **PROFILE** (`profile.py`/`schema.py`) parses and validates
a portfolio, rejecting an incomplete or self-contradictory debt at
construction time; **ADJUST** (`adjust.py`) computes each debt's true
effective cost from verified tax (`tax_rules.py`) and fee (`fee_rules.py`)
rules; **SEQUENCE** (`sequence.py`) produces the naive and adjusted
orderings and attributes every divergence to its mechanism; **IMPACT**
(`impact.py`) simulates both orderings month by month with a real
waterfall (freed-up minimum payments roll forward into the next-priority
debt's surplus -- the "snowball" effect an earlier, buggy version of this
simulation got wrong, see DECISIONS.md) and reports the real cost
difference. **EXPLAIN** (`explain.py`) is the one file that calls a model
(Sarvam's `sarvam-105b`), turning the computed plan into Dhruva-style
prose, required to state each divergence's correct kind of claim and never
let an unfavorable cost comparison go unstated.

## Running it

```
uv sync
uv run pytest                                     # 49 tests, deterministic core + eval heuristics + API
uv run python demo_checkpoint.py                  # regenerates samples/, prints both orderings for all 7
uv run uvicorn api:app --reload                   # POST /assess, GET /health
uv run python -m eval.manifest                     # regenerates eval/manifest.json
uv run python -m eval.collect --experiment X --split tune validation --repeats 2
uv run python -m eval.metrics --experiment X       # prints the faithfulness report
```

`explain.py`, `eval/collect.py`, and `POST /assess` with `explain: true`
need `SARVAM_API_KEY` in a `.env` file (gitignored) and make real, billed
API calls -- `pytest` never does.
