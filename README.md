# TrueOrder

A debt-repayment sequencing engine for a mixed Indian debt portfolio (credit
cards, personal/home/auto/education loans) that computes a tax-and-fee-
adjusted repayment order alongside the naive avalanche order most tools and
AI assistants give today, and shows exactly where, why, and how reliably
they diverge.

## The gap

Asked directly -- *"Hmmmm, tell me, ig I hypothetically had 5 EMIs and 4
credit cards, are you able to tell me the order in which to repay them
efficiently?"* -- Dhruva, Oolka's in-app AI assistant, returns the two
textbook heuristics.

![Dhruva, Oolka's in-app AI assistant, answering a debt-ordering question with the avalanche and snowball heuristics only](docs/dhruva_naive_avalanche.png)

*Dhruva, 06/09/2026 09:02 PM. Asked the question above, it offers "Avalanche
Method (Save Interest)" -- list debts by interest rate, highest rate first --
and "Snowball Method (Quick Wins)" -- list by balance size, smallest balance
first -- then, under a bolded "My advice:", "Credit cards usually have much
higher interest rates than personal loans, so they are often the best place
to start regardless of the method." The bubble is clipped mid-word there by
the phone's scroll fold. Nowhere in the visible response is there any mention
of tax regime, prepayment-charge asymmetry, or credit-utilisation tension,
and no question is asked about any of them.*

Both heuristics rank on a single snapshot field: stated rate, or balance.
Neither asks which tax regime the borrower is in, though Section 24(b) is
capped at Rs 2,00,000 for a self-occupied property under the old regime and
blocked outright under the new one (Section 115BAC); neither asks whether a
property is self-occupied or let out, though that changes the same loan's
after-tax cost; and neither distinguishes a floating-rate loan from a
fixed-rate loan at the same stated APR, though only the fixed-rate one can
carry a foreclosure charge at all -- prepayment charges on floating-rate
loans to individuals for non-business purposes have been prohibited since
RBI/2019-20/29 (2 Aug 2019) and are now consolidated under the RBI
(Pre-payment Charges on Loans) Directions, 2025. Full citations with source
URLs are in [tax_rules.py](tax_rules.py) and [fee_rules.py](fee_rules.py);
every rule this project applies carries one.

Beyond the assistant -- and this is what I personally saw in the Oolka app in
September 2026, not a sourced claim: the Cards/Loans tabs each showed one
instrument at a time, and the premium tier on offer was utilisation alerts
and bureau-dispute automation -- genuinely useful, but not avalanche/snowball
optimization or lump-sum-split guidance across a portfolio.

Naive avalanche isn't wrong in general -- for an all-unsecured portfolio
with no tax-advantaged debt, it's the right answer, and this project's own
"agreement case" sample ([samples/sample_001_agreement_case.json](samples/sample_001_agreement_case.json))
confirms the two orderings converge exactly when nothing distinguishes them.
It's wrong specifically in the cases that produce a genuine conflict, and
those are what the rest of this README is about. See
[RUNBOOK.md](RUNBOOK.md) for the full manual process this replaces, step by
step.

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

(A fourth label, `displaced`, appears in the output but is *not* a fourth
objective -- it marks a debt whose rank moved only because a neighbour was
promoted past it, so it makes no claim of its own and names the debt that
moved it instead. It exists because the alternative, borrowing the causing
debt's label, produced statements that were flatly untrue: a credit card
tagged as having a foreclosure-charge problem, which a revolving facility
cannot have.)

That much would already justify keeping these objectives separate
(`schema.DivergenceMechanism`, `DivergenceRationale`, enforced by a
validator that makes `traded_for` required for utilisation and forbidden
for tax/fee -- see [DECISIONS.md](DECISIONS.md)). But there's a second, deeper layer,
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
two unrelated quirks (see [DECISIONS.md](DECISIONS.md)'s "one root cause, not two" entry).
Verified directly, not assumed: sweeping this project's own eval manifest
for the affected tax segment shows three portfolios where the adjusted
order comes out cheaper and three where it comes out very slightly more
expensive -- same mechanism, same attribution logic, opposite outcome,
depending only on where each portfolio happens to sit in its amortization.

## Worked example: the same mechanism, the same segment, opposite outcomes

A *segment*, here and below, is a named synthetic-portfolio archetype built
to exercise one specific mechanism -- `synth/generator.py` produces six
portfolios per segment, varying the numbers while holding the mechanism
fixed.

Both of the following are real, unedited `explain()` outputs for the exact
same segment (`letout_home_old_regime_loss_capped` -- an old-regime,
let-out home loan whose interest exceeds the Section 71(3A) cap) --
different portfolios, same divergence, same tax mechanism correctly
identified in both. The only thing that differs is where each portfolio's
numbers land relative to the cap, which `sequence.py`'s upfront ranking has
no way to know.

**Where it works as the ranking implies** (`letout_home_old_regime_loss_capped_004`, net_cost_delta = **+Rs 3,552.60**):

> The engine's adjusted order is cc1, then pl1, then h1. [...] Because you
> are on the old tax regime and this is a let-out property, the interest
> you pay is genuinely deductible. The deductible amount this year is Rs
> 270,000, which at your 30% marginal rate gives you a real annual tax
> saving of Rs 81,000. [...] **the adjusted sequence saves you Rs 3,552.60
> in net cost** over the full repayment compared to simply following the
> naive high-rate-first method.

**Where it doesn't** (`letout_home_old_regime_loss_capped_002`, net_cost_delta = **-Rs 1,384.54**):

> The adjusted order [...] is cc1, then pl1, then h1. [...] Your home loan
> (h1) has a genuine rupee saving of Rs 81,000 per year. Under the old tax
> regime, your let-out property generates a deductible home-loan interest
> amount of Rs 270,000 this year [...] That is why the engine treats the
> home loan (h1) as lower cost than its stated rate would suggest. [...]
> When simulated with your given monthly surplus for this portfolio, the
> adjusted order does not deliver a cheaper outcome. [...] **the adjusted
> order costs Rs 1,384.54 more than the naive order**, so the adjusted
> sequence is slightly more expensive in this case.

Same mechanism, same reasoning, opposite outcome. Both explanations pass
every check in `eval/metrics.py` -- they are two of the 58/58 baseline and
26/26 held-out calls that did. Neither is wrong; the second is simply
honest about an unfavorable number instead of assuming the mechanism's
usual reliability applies here too. That honesty is the entire point:
`explain.py`'s system prompt requires stating the real simulated
comparison exactly as computed, never inferring it from which mechanism
fired.

Both also demonstrate the `displaced` label in use -- each correctly says
the personal loan "carries no adjustment of its own" and moved "only
because h1 was promoted past it", rather than attributing a tax reason to
a debt that has none.

## Eval results

Ground truth is generated by this project's own deterministic core --
`eval/manifest.py` builds 42 cases across all 7 named segments (6 each);
`eval/collect.py` calls `explain()` twice per case; `eval/metrics.py` grades
each explanation against what `sequence.py`/`impact.py` actually computed
for that exact portfolio.

**Baseline (`tune`+`validation`, 2 repeats/case, 0 errors, Rs 37.29):
100% faithfulness (58/58 calls).**

**Held-out `test` split (2 repeats/case, 0 errors, Rs 18.48): 100%
faithfulness (26/26 calls).**

Read both as **lower bounds**, not exact measures. Across two full
collection runs, eleven separate defects were found in the grading
heuristics themselves -- and every single one was a FALSE NEGATIVE, a
correct and honest explanation scored as a failure. Sign-blind number
matching flagged a correctly restated "costs Rs 949.66 more" as fabricated
because ground truth stored it as `-949.66`. A false-claim detector with no
negation handling read "there are no tax deductions" as *claiming* one. An
order check anchored itself to the wrong occurrence of a repeated debt ID.
And five separate times, a perfectly honest admission used a phrasing
nobody had enumerated yet -- "costs slightly more", "the net cost rises
to", "Rs 587.64 above the naive order's", "costs you an extra Rs 240.11".
Not one defect ever let a bad explanation through. That asymmetry is
structural rather than lucky: matching a finite list of phrasings can only
miss ways of saying a true thing, never manufacture evidence for a false
one. Closing the remaining gap needs a model-graded judge, not a longer
regex. Every one of the eleven is now a permanent regression test in
`tests/test_eval_metrics.py`, pinned with the literal string that exposed it.

Both numbers were independently recomputed from the raw JSONL with
separately written extraction and matching logic, rather than trusting
`metrics.py`'s own output -- 58/58 and 26/26 on every independently
checkable dimension.

**On the held-out split being opened twice.** `eval/TEST_SET_ACCESS_LOG.jsonl`
records two accesses, not one, and that is the honest record. The first
graded a version of the engine that no longer exists: three subsequent
correctness fixes (a foreclosure-fee inconsistency between stages, the
Section 24(a) omission, and the displaced-mechanism relabel) all changed
ground truth, which invalidated the first result outright. Re-opening was
not iteration against test-set feedback -- **no prompt tuning happened
between the two runs**, `eval/experiments.py` was never built, and the
manifest's split membership is byte-identical across both (verified, not
assumed). What the second access measures is the same discipline applied to
a corrected engine, and the log exists precisely so this is visible rather
than quietly presented as a single clean pass.

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

Four deterministic stages, zero LLM calls, enforced by an AST-based test
(`tests/test_no_llm_imports.py`) that would fail if any of the four ever
imported one -- **PROFILE** (`profile.py`/`schema.py`) parses and validates
a portfolio, rejecting an incomplete or self-contradictory debt at
construction time; **ADJUST** (`adjust.py`) computes each debt's true
effective cost from verified tax (`tax_rules.py`) and fee (`fee_rules.py`)
rules; **SEQUENCE** (`sequence.py`) produces the naive and adjusted
orderings and attributes every divergence to its mechanism; **IMPACT**
(`impact.py`) simulates both orderings month by month with a real
waterfall (freed-up minimum payments roll forward into the next-priority
debt's surplus -- the "snowball" effect an earlier, buggy version of this
simulation got wrong, see [DECISIONS.md](DECISIONS.md)) and reports the real cost
difference.

A fifth stage, **EXPLAIN** (`explain.py`), sits outside that deterministic
core as the one and only file that calls a model (Sarvam's
`sarvam-105b`) -- turning the computed plan into Dhruva-style prose,
required to state each divergence's correct kind of claim and never let an
unfavorable cost comparison go unstated. It is deliberately exempt from the
AST check above, and that exemption is itself tested: one test asserts
explain.py is the ONLY project file importing an LLM SDK, another asserts
the deterministic `/assess` path reaches the Sarvam SDK zero times.

## Running it

```
uv sync
uv run pytest                                     # 108 tests, deterministic core + eval heuristics + API
uv run python demo_checkpoint.py                  # regenerates samples/, prints both orderings for all 7
uv run uvicorn api:app --reload                   # POST /assess, GET /health
uv run python -m eval.manifest                     # regenerates eval/manifest.json
uv run python -m eval.collect --experiment X --split tune validation --repeats 2
uv run python -m eval.metrics --experiment X       # prints the faithfulness report
```

`explain.py`, `eval/collect.py`, and `POST /assess` with `explain: true`
need `SARVAM_API_KEY` in a `.env` file (gitignored) and make real, billed
API calls -- `pytest` never does.
