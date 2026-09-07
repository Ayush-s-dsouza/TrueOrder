# Decisions

Every non-trivial choice in this project, with the alternative it rejected.
Appended to as the build progresses, not written retroactively at the end.
Structure and discipline ported from Prequal's `DECISIONS.md`, whose final
entry names this project as its intended successor.

## Section 80E is not available under the new tax regime -- the brief's assumption was wrong

The project brief flagged this as unverified and asked for a web-search
check before writing any code: "Section 80E education loan interest
deduction (uncapped, 8 years from first repayment, available in which
regime)... verify current rules yourself." The brief's own scope section
additionally stated the deduction is "available regardless of regime --
VERIFY this last point, don't assume." Verification found that assumption
false: Section 115BAC's list of permitted deductions under the new regime
does not include Section 80E at all. It is old-regime-only.

**Decision**: `tax_rules.education_loan_deduction()` returns zero deductible
amount whenever `regime == "new"`, regardless of how far inside the 8-year
window the loan is, with a note stating the regime is the reason. Two
permanent regression tests exist for this
(`tests/test_tax_rules.py::test_education_loan_under_new_regime_has_zero_tax_adjustment`
and the window-lapsed sibling test), both added as *required*, not optional,
after a code review flagged that proving 80E activates without also
proving both ways it deactivates would reopen the exact "confidently wrong
until someone checks" failure mode this project exists to catch.

**Rejected alternative**: encoding the brief's original "regardless of
regime" assumption directly, which would have been silently wrong for
every new-regime borrower with an education loan -- exactly the class of
error (a plausible-sounding tax claim that happens to be false) this
project's entire premise is built around preventing.

## Let-out home loans need an explicit rental-income input, not just regime + occupancy

Initial schema design treated a home loan's tax adjustment as a function of
`(regime, occupancy)` alone. Verifying Section 24(b) and Section 71(3A)
in detail surfaced a real complication: for a let-out property, the
interest deduction against rental income is uncapped in *both* regimes, but
whether a resulting loss (interest exceeding rental income) can be set off
against other income differs by regime -- old regime allows up to
Rs 2,00,000/year (Section 71(3A)); the new regime (Section 115BAC) blocks
inter-head set-off of house-property loss entirely. Modeling this correctly
requires knowing how much rental income actually exists, not just that the
property is let out.

**Decision**: `HomeLoan.annual_rental_income` is a required field whenever
`occupancy == let_out`, enforced by a raising `model_validator` (see next
entry) rather than defaulted or assumed. `tax_rules.home_loan_deduction()`
computes `rental_offset = min(annual_interest, annual_rental_income)`
first, then applies the regime-dependent loss-set-off rule only to the
remainder.

**Rejected alternative**: assuming rental income always fully absorbs the
interest (i.e. no loss ever arises), which would have quietly produced the
same answer in both regimes for a let-out property and hidden the entire
old-regime-vs-new-regime distinction this case exists to demonstrate.

## Validators raise on violation; they do not default to "no adjustment"

A code review flagged that a validator merely *documented* as forbidding a
field combination is a weaker guarantee than one that actually raises --
"forbidden via a validator versus the field simply not existing are
different guarantees," specifically comparing this to Prequal's
`ThresholdField` provenance validator, which raises rather than silently
accepting an incomplete value.

**Decision**: every cross-field invariant in `schema.py`
(`ForeclosureFieldsMixin._foreclosure_charge_matches_rate_type`,
`HomeLoan._rental_income_matches_occupancy`) raises `ValueError` on
violation in *both* directions -- a floating-rate loan with a non-null
charge is rejected, and so is a fixed-rate loan with a null one; a
self-occupied home loan with rental income set is rejected, and so is a
let-out one without it. `tests/test_schema.py` has one test per direction
per validator (four total), each constructing an otherwise-valid debt with
exactly one deliberate violation and asserting `ValidationError`, so the
strictness itself is checked, not just documented.

**Rejected alternative**: defaulting `foreclosure_charge_pct` to `None`
when a floating-rate loan reports one (silently discarding bad input) or
defaulting a missing charge on a fixed-rate loan to `0` (silently assuming
no charge when the truth is "unknown") -- both would make bad input
indistinguishable from confirmed-absent input, exactly the ambiguity this
project's entire adjustment-note discipline exists to eliminate.

## Six sample portfolios, not five

The brief specified five sample portfolios. A code review of the plan
pointed out that none of the five exercises Section 80E at all -- the
all-unsecured "agreement case" deliberately has no deductible debt, and no
other sample includes an education loan -- which would have left 80E living
only as prose in `tax_rules.py`, with its activation path never actually
asserted against in code.

**Decision**: added a sixth segment, `education_loan_80e_old_regime`, plus
a required pair of off-case regression tests (see the first entry above).

**Rejected alternative**: folding an education loan into one of the
existing five samples instead of adding a sixth. Rejected because each of
the original five is already load-bearing for a specific, cleanly
demonstrated divergence (or, for the agreement case, the deliberate absence
of one) -- adding a second dimension to any of them would muddy which
adjustment caused which rank change, undermining the "hand-worked
expectation" discipline `tests/test_sequence.py` depends on.

## Effective cost combines tax and fee adjustments as independent deltas from the stated rate, not compounded

`after_tax_rate_pct` and `foreclosure_adjusted_rate_pct` are both computed
directly from `stated_apr_pct` in `tax_rules.py`/`fee_rules.py`, matching
the brief's own phrasing ("after_tax_rate = stated_rate, unless...",
"foreclosure_adjusted_rate = stated_rate + ..., else unchanged" -- both
relative to the stated rate, not to each other).

**Decision**: `adjust.py` combines them as
`effective_cost_rank_input = stated_rate + (after_tax_rate - stated_rate) + (foreclosure_adjusted_rate - stated_rate)`
-- i.e. the tax-shield discount and the foreclosure-charge surcharge are
independent deltas, summed.

**Rejected alternative**: applying the foreclosure adjustment on top of the
already-tax-adjusted rate (compounding). Rejected because the two
adjustments have no principled interaction -- a tax authority's treatment
of interest has nothing to do with a lender's prepayment terms -- and
compounding them would make the size of one adjustment depend arbitrarily
on which order they happened to be applied in.

## The utilisation-crossing heuristic is a binary override, not a rate-equivalent number

The 30% aggregate-utilisation threshold is real; the commonly-cited
"30-80 point" CIBIL-score impact is not a precise, published bureau figure
(see `fee_rules.UTILISATION_HEURISTIC_DISCLAIMER`). Converting an
uncertain point-score range into a fabricated interest-rate-equivalent
number would overstate the heuristic's precision.

**Decision**: `adjust._utilisation_priority_scores()` returns a binary
1.0/0.0 signal -- 1.0 iff paying off this specific card would move the
portfolio's aggregate utilisation from above 30% to at-or-below it.
`sequence.adjusted_order()` applies it as an explicit post-sort override:
every card with a nonzero score is promoted ahead of every non-crossing
debt, ranked among any other crossing cards by their own effective cost.

**Rejected alternative**: converting the heuristic into a fake rate bonus
(e.g. "+15 percentage points") and blending it into
`effective_cost_rank_input` alongside the tax/fee deltas, which would make
an admittedly-uncertain heuristic look exactly as precise as a verified RBI
rate adjustment in the output.

## Education loans carry no modeled foreclosure/fee dimension

RBI's 2019 circular and the 2025 Pre-payment Charges Directions name
education loans among the floating-rate term loans covered by the
no-foreclosure-charge prohibition, which would suggest adding
`rate_type`/`foreclosure_charge_pct` to `EducationLoan` for completeness.

**Decision**: left out. Education loan's defining dimension in this
project's five-debt-type scope is Section 80E; the fee dimension is fully
covered by the other four debt types (home/personal/auto loans span both
floating-exempt and fixed-chargeable cases already). `fee_rules.py`'s
`loan_foreclosure_adjustment()` explicitly notes this scope decision at the
point where a reader would otherwise expect to see it.

**Rejected alternative**: adding the fields anyway "for completeness,"
rejected per this project's own no-premature-abstraction principle -- a
field that always resolves the same way (no fixed-rate education loan
sample exists, or is planned, in this scope) adds surface area without
adding a new demonstrated case.

## Credit card "not applicable" is represented in the note, never as a NaN sentinel

An early draft of `fee_rules.credit_card_foreclosure_note()` returned
`foreclosure_adjusted_rate_pct=float("nan")` to represent "foreclosure
doesn't apply to a revolving facility." Caught during implementation,
before it reached a test: NaN comparisons are silently unreliable (NaN <
NaN is False, sorting behavior is undefined), which would have corrupted
`sequence.py`'s cost-based sort without raising any visible error.

**Decision**: the function takes `stated_rate_pct` and returns it
unchanged; "not applicable" (as distinct from "zero charge, confirmed
absent") is stated only in the note text, never encoded as a numeric
sentinel.

**Rejected alternative**: using `None` instead of NaN, which would have
required every downstream consumer of `foreclosure_adjusted_rate_pct` to
handle an optional numeric field solely for one debt type -- more
complexity for the same information the note already carries unambiguously.

## Marginal tax rate is a required input, not computed from income slabs

Computing the after-tax value of a deduction requires a marginal tax rate.
India's actual slab system (old vs. new regime, plus surcharge and cess
thresholds) is its own significant verification burden, and getting it
wrong would be exactly the kind of confidently-wrong tax claim this project
exists to avoid producing.

**Decision**: `Portfolio.marginal_tax_rate_pct` is a required field with no
default -- the caller states their own bracket directly.

**Rejected alternative**: deriving marginal rate from a stated annual
income plus regime, which would require encoding, verifying, and
maintaining the full slab/surcharge/cess schedule (which changes most
Finance Acts) for a feature orthogonal to this project's actual value
proposition of debt-repayment sequencing.

## AST no-LLM-imports check: fixed a latent bug found while porting Prequal's version

Prequal's `tests/test_no_llm_imports.py` includes `"google.genai"` in its
forbidden-roots set. Since the check's own root-extraction always splits an
imported module's dotted path on `"."` and keeps only the first segment, a
forbidden-roots entry containing a `.` can never match anything --
`import google.genai` resolves to root `"google"`, not `"google.genai"`.

**Decision**: TrueOrder's `FORBIDDEN_IMPORT_ROOTS` lists `"google"` as the
root instead. The positive-canary test (asserting the eventual LLM-calling
module really does import an SDK) is deferred until `explain.py` exists,
since there is no LLM-calling module yet this phase -- a canary test
written today would have nothing to canary.

**Rejected alternative**: copying Prequal's set verbatim, which would have
carried the latent bug forward into a project whose research phase already
found and corrected two other inherited-assumption errors -- leaving a
known-broken check in place would be inconsistent with that standard.

## impact.py's first waterfall silently shrank the total budget every time a debt cleared

The first version of `simulate_waterfall` kept `monthly_surplus` fixed
forever and simply stopped paying a finished debt's minimum -- it never
redirected that freed-up capacity anywhere. Every checkpoint sample's
`net_cost_delta` came out favoring the NAIVE order, including the tax-driven
divergence cases (`letout_home_old_regime`, `education_loan_80e_old_regime`)
where the adjusted order should reliably win once tax benefit is properly
realized over time. That result contradicted a hand-derived proof (a
"weighted balance-over-time" exchange argument) that ranking by after-tax
rate should minimize net cost -- a strong signal the discrepancy was a bug,
not a real finding, and it was traced by instrumenting month-by-month
per-debt payoff timing on `sample_002_letout_home_old_regime`: under the
adjusted order, `h1` (home loan) only started receiving accelerated
payments once `pl1` (personal loan) cleared at month 14, and `pl1`'s freed
Rs 9,000/month minimum then simply vanished instead of compounding into
`h1`'s payment -- delaying `h1`'s own payoff by exactly that gap, with no
compensating benefit.

**Decision**: `simulate_waterfall` now computes a fixed
`total_monthly_capacity = sum(all original minimums) + monthly_surplus`
once, and recomputes `surplus_this_month = total_monthly_capacity -
(minimums still owed by currently active debts)` fresh every month -- so
freed capacity from a paid-off debt automatically rolls into next month's
surplus for the next-priority debt (the standard "snowball" effect).
`tests/test_impact.py::test_freed_minimum_payment_rolls_forward_to_the_
next_priority_debt` is a direct regression: it constructs a debt whose own
minimum payment exactly breaks even against its own interest (guaranteed
non-payoff on minimum alone), so the old bug would have made this specific
test hang until `MAX_SIMULATION_MONTHS` and raise.

**Rejected alternative**: keeping `monthly_surplus` fixed and documenting
the freed-minimum loss as an intentional "conservative" assumption.
Rejected because it isn't conservative, it's wrong -- no realistic
household stops budgeting money toward debt once one card is paid off, and
the resulting numbers were actively misleading (every divergence case
looked like the adjusted order was worse, when for the tax cases it should
provably not be).

## "Adjusted = cheaper" was never a valid blanket claim -- the project's central finding

This is the single most important discovery in TrueOrder, and it changes
how "adjusted" must be described everywhere: in schema field names,
docstrings, and eventually the README and `explain.py`'s prose. It is not a
footnote to the waterfall bug fix above -- it would have been true even if
that bug had never existed.

After fixing the roll-forward bug, the tax-driven divergence samples
correctly showed the adjusted order as net-cheaper. The fee-driven sample
(`fixed_auto_foreclosure`) and the utilisation-heuristic sample
(`utilisation_threshold`) still showed the adjusted order as slightly net-
COSTLIER. Tracing both by hand (instrumenting per-debt payoff months and
pre-payoff balances) showed this was not a second bug -- it was proof that
"the adjusted order" was always doing three structurally different things
at once, silently merged into one ranking and one "cheaper/not cheaper"
framing:

1. **TAX** -- a verified deduction lowers a debt's true cost. The tax
   benefit is a continuous, ongoing percentage of actual accrued interest,
   the same "weighted balance over time" shape as the interest cost it
   discounts -- so ranking by after-tax rate provably aligns with
   minimizing net cost, and does in every tax-driven sample
   (`letout_home_old_regime`, `education_loan_80e_old_regime`,
   `letout_home_old_regime_loss_capped`). **Mechanically cheaper, always,
   when it fires.**
2. **FEE** -- a verified foreclosure charge raises a debt's true cost
   above its stated rate. But the charge is a ONE-TIME cost proportional to
   whatever balance remains at the moment of payoff, not a continuous rate
   -- it does not scale with "how long you delay" the way a tax shield
   does. In `fixed_auto_foreclosure`, promoting `a1` (9% nominal) ahead of
   `pl1` (11% nominal, genuinely the more expensive debt) because `a1`'s
   fee-annualized ranking number (11.67%) looks worse increases total
   nominal interest by more (~Rs 2,314) than the one-time fee difference
   saves (~Rs 27). **Correctly identifies a debt as more expensive than
   naive assumes; can come out either cheaper or slightly costlier once
   realized in a real waterfall.** This is a ranking justification, not a
   savings guarantee.
3. **UTILISATION** -- a heuristic override that protects a CIBIL score,
   not rupees. In `utilisation_threshold`, `cc2`'s adjusted rate is
   IDENTICAL to its stated rate (30%, no tax or fee adjustment at all); it
   is promoted purely to cross the 30%-aggregate-utilisation threshold.
   Promoting it ahead of `pl1` (genuinely 32% nominal) costs a little more
   real interest (~Rs 251); that cost IS the price of the trade, not a
   modeling failure. **Explicitly not a cost-savings claim of any kind.**

Stating a utilisation promotion as a "cost saving" -- or a fee promotion as
an unconditional one -- is a category error about what kind of claim is
being made, not a wrong number. That is a worse failure than any tax
miscalculation, because a wrong number can be checked against the
computed output; a category error can look completely plausible while
answering a different question than the one asked. Since `explain.py`'s
prose (built in a later phase) is the one place an LLM touches this
project's output, and the eval measures whether that prose is faithful to
what was computed, this distinction has to be correct and machine-checkable
BEFORE `explain.py` or `eval/` exist -- otherwise the eval would be
grading explanations against a ground truth that itself conflates three
different kinds of claims.

**Decision**: `schema.py` adds `DivergenceMechanism` (`tax` / `fee` /
`utilisation`) and `DivergenceRationale` (`mechanism`, `net_rupee_effect`,
`traded_for`), and `RepaymentOrdering.divergence_rationale` requires
exactly one entry per divergence point -- a divergence is never left as a
bare rank change with no stated mechanism. `DivergenceRationale` itself
enforces the asymmetry with a validator: `traded_for` is REQUIRED for
`utilisation` (the one mechanism that must never let its non-rupee nature
go unstated) and FORBIDDEN for `tax`/`fee` (which are rupee claims on their
own and must not be diluted with a trade-off framing that doesn't apply to
them). `sequence.py`'s `compute_divergence_rationale` attributes each
divergent debt to its own mechanism when it has one, or -- for a debt that
merely got passively displaced by a neighbor's promotion (most divergences
in this project's samples: e.g. `pl1` in `letout_home_old_regime` has no
adjustment of its own at all) -- borrows the mechanism of whichever other
divergent debt actually caused the shift, keeping `net_rupee_effect` at
0.0. A debt with more than one mechanism active at once (e.g. a
hypothetical fixed-rate let-out home loan) raises rather than silently
picking one, since guessing there would reintroduce the exact category-
error risk this decision exists to eliminate.

That raise is proven at two separate levels, not one: `test_schema.py`
proves `DivergenceRationale` itself cannot be CONSTRUCTED with more than
one mechanism (the type-level guarantee); `test_sequence.py`'s
`test_compound_tax_and_fee_on_the_same_debt_raises_through_the_real_
pipeline` separately proves the PIPELINE never TRIES to build one when a
real, ambiguous portfolio reaches it -- a fixed-rate, let-out home loan
under the old regime, fed through `compute_ordering` (the actual entry
point, not the internal helper called directly), confirmed to trigger both
`tax_delta` and `fee_delta` on the same debt and then confirmed to raise.
A type-level guarantee alone would leave open the possibility that
`adjust.py` or `sequence.py` never actually exercises the ambiguous case in
practice -- proving the validator works is not the same claim as proving
the pipeline reaches it, and this project's five real debt types do
include exactly one shape (a home loan with `rate_type=fixed` and
`occupancy=let_out`) capable of triggering it, however atypical in real
Indian lending practice.

`impact.py` and its tests are unchanged in behavior but reframed in every
docstring/name to match: `net_cost_delta > 0` is a REQUIRED regression for
every tax-driven sample; `net_cost_delta`'s sign for the fee-driven sample
is pinned as a verified fact about these specific numbers, not asserted as
a general property of the fee mechanism (a comment says so explicitly, so
a future change to adjust.py's fee formula or sample 3's numbers is a
prompt to re-verify which way the trade-off goes, not to blindly flip the
assertion); and `net_cost_delta` is explicitly documented as NOT the metric
that judges the utilisation-driven sample's correctness at all -- its
`DivergenceRationale.traded_for` is.

**Rejected alternative**: changing SEQUENCE's ranking formula to force
fee/heuristic-driven orderings to also minimize `net_cost` (e.g. converting
the foreclosure charge into a continuous-rate equivalent, or dropping the
utilisation override when it doesn't pay for itself). Rejected for two
reasons: SEQUENCE's current design was already reviewed and checkpointed
with specific, tested orderings for all seven samples, and revising it now
without being asked would relitigate settled work; and more fundamentally,
the utilisation heuristic was never supposed to be judged by `net_cost` at
all -- forcing it to also win on rupees would hide the real trade-off a
borrower is making instead of naming it.

## Git repo scoped to TrueOrder/ itself

`Desktop` (the parent of `TrueOrder/`) is itself an unrelated, uncommitted
git repository containing unrelated personal files.

**Decision**: `git init` run inside `TrueOrder/` directly, giving it its
own independent history, matching Prequal's own git-scoping decision.

**Rejected alternative**: none considered -- committing TrueOrder as part
of the `Desktop` repo's history was never viable given that repo's
unrelated, pre-existing untracked contents.

## explain.py uses Sarvam, not Claude, per explicit user choice

Before writing explain.py, the model/provider question was put to the
user directly (a real cost decision, since the eval calls it dozens of
times per run) with Claude Sonnet 5/Opus 5/Haiku 4.5 as the offered
options. The user's actual answer named Sarvam instead, along with a live
API key pasted directly into the conversation.

**Decision**: `explain.py` is built exactly on Prequal's
`author_criterion.py` pattern -- `ExplanationProvider` Protocol,
`SarvamProvider` as the sole implementation, `sarvam-105b` as the model
(same as Prequal, same verified pricing). The pasted key was written
immediately to a `.env` file (confirmed gitignored before anything else
touched the repo) and is read only via `os.environ["SARVAM_API_KEY"]` --
never hardcoded, never echoed in any output or commit.

**Rejected alternative**: defaulting to Claude Opus 5 per this session's
own tooling default. Rejected because the user's answer is what it is --
an explicit instruction overrides a tool's default recommendation, and
Sarvam also matches this project line's established precedent (Prequal).

## sarvam-105b's real latency and reasoning-token cost, discovered by running it, not assumed

Prequal's author_criterion.py documented sarvam-105b as a reasoning model
whose chain-of-thought counts against the same token budget as the final
answer, with `max_tokens=4096` as its own working value for a short
JSON-extraction task. explain.py's task is a longer, six-rule,
per-mechanism-framing prose generation -- a materially different
reasoning load -- and assuming the same 4096 budget would carry over
untested was exactly the kind of assumption this project's whole research
phase has been built around not making.

Verified directly: at `max_tokens=4096` and even `8000`, real calls
returned `finish_reason="length"` with `message.content=None` -- the
model spent the entire budget on chain-of-thought (27,208 characters of
`reasoning_content` at the 8000-token attempt) and never reached a final
answer. A real call only succeeded at `max_tokens=20000` (8,712 completion
tokens for a two-divergence-point case). Separately, the client's default
read timeout was too short for this latency profile -- one call timed out
outright during eval smoke-testing (a `ConnectTimeout`, not an API error)
even after the `max_tokens` fix.

**Decision**: `max_tokens=32_000` (well above the observed 8,712-token
figure, for headroom on portfolios with more divergence points), and an
explicit `timeout=180.0` on the `SarvamAI` client. Both are documented in
`explain.py` with the actual observed numbers, not a round guess.

**Rejected alternative**: copying Prequal's `max_tokens=4096` on the
assumption that "it's the same model, so the same budget should hold" --
disproven directly by running it, in well under the time it would have
taken to debate the assumption.

## The debt-ID and explicit-sequence prompt rules exist for the eval, and for real users

Two SYSTEM_PROMPT rules were added specifically because real collected
transcripts, not hypotheticals, showed correct explanations that were
nonetheless unverifiable by the eval's text heuristics:

1. The model naturally described debts by type ("your home loan") rather
   than by `debt_id`, correct and readable, but leaving nothing for a
   metric to anchor a per-debt check on.
2. On one case, the model described a reordering as a narrative ("keeps
   cc1 on top, but swaps pl1 and cc2") without ever listing the full
   adjusted sequence explicitly -- also correct, but not something a
   sequence-matching check could verify.

**Decision**: added a rule requiring each debt's ID in parentheses on
first mention, and a rule requiring the full order to appear somewhere as
an explicit sequence (in addition to, not instead of, any narrative
description). Both were re-verified against real calls before being
trusted. Both also have a genuine product justification independent of
the eval: a debt ID lets a reader cross-reference their own statements,
and an explicit sequence gives an unambiguous bottom line a narrative
alone doesn't -- these are prompt improvements the eval's needs happened
to surface, not eval-gaming.

**Rejected alternative**: building fuzzier NLP (e.g. detecting "swap"
narratives and resolving them into an implied sequence) to grade the
original, unconstrained prose instead of constraining the prose. Rejected
because it would have added real complexity to correctly interpret
language the model wasn't even asked to make checkable, when asking it
directly was simpler, more robust, and improved the product too.

## Three real bugs found and fixed in eval/metrics.py's own heuristics, before trusting any faithfulness number

Building the eval surfaced three false positives in the metrics
themselves, each found by comparing a metric's verdict against a real
collected explanation whose correctness had already been manually
verified -- the same discipline as tax_rules.py's and impact.py's earlier
bug hunts, applied to the eval's own code this time:

1. **Sign-insensitive number matching.** A `net_cost_delta` of -949.66 was
   correctly restated in prose as "the adjusted order costs Rs 949.66
   more" (a natural, correct sign flip for that phrasing) -- flagged as an
   invented number by a signed-value comparison. Fixed: `_numbers_match`
   now compares `abs(a)` against `abs(b)`.
2. **Negation-blind tax-claim detection.** "There are no tax deductions"
   matched the false-tax-claim pattern on its "tax deduction" substring
   and was flagged as a fabricated benefit -- exactly backwards, since the
   sentence correctly DENIES one applies. Fixed: `_is_negated` checks for
   a denial cue ("no", "not", "does not", ...) within 40 characters before
   any match before counting it as a violation.
3. **Order-checking anchored on each debt's first occurrence ANYWHERE in
   the text.** Since naive order is conventionally stated first in prose,
   this silently verified the NAIVE sequence instead of the adjusted one
   whenever they shared a debt at different positions -- caught because a
   genuinely correct explanation scored `order_correct=False`. A marker-
   phrase anchor ("adjusted order") was tried next and also failed: real
   text used "adjusted plan", or led with the recommendation before any
   label at all. Fixed: `adjusted_order_sequence_correct` now searches for
   the adjusted sequence's exact debt-ID pattern as a tight, contiguous run
   anywhere in the text, independent of any label phrase.

**Decision**: all three are permanent regression tests in
`tests/test_eval_metrics.py`, using literal text fixtures (no API calls
needed) reproducing each real failure shape. `eval/metrics.py`'s own
docstrings document each heuristic as necessary-but-not-sufficient where
that's true (e.g. `utilisation_correctly_framed` proves the right
vocabulary appears, not that no contradicting claim exists elsewhere).

**Rejected alternative**: trusting the first faithfulness numbers the
metrics produced (a 0% headline rate on the first smoke-test batch)
instead of investigating why they contradicted the manually-verified
quality of the same explanations. A metric that disagrees with a
independently-confirmed ground truth is a bug report about the metric,
not a bug report about the thing being measured -- treating it as the
latter would have meant shipping a faithfulness eval that was itself
unfaithful.

## SECOND correction to the tax guarantee: the Rs 2L cap breaks the constant-shield-fraction assumption too

This is the most important finding of the whole eval run, and it corrects
a claim this project made confidently, in writing, in multiple files
(schema.py, DECISIONS.md, test_impact.py, test_sequence.py): that the TAX
mechanism is "mechanically cheaper, ALWAYS, when it fires" -- stated as an
unconditional guarantee, with a test marked "if this ever fails, that is a
real bug." Running the FULL 42-case eval manifest (not just the 3
hand-picked cases used during development) surfaced 3 negative
`net_cost_delta` values, all for `letout_home_old_regime_loss_capped`, all
for indices this project had never individually inspected before
(`_000`, `_002`, `_005` under the eval's own seed -- a DIFFERENT seed from
the one used when this segment's single tested index, under the
checkpoint seed, happened to come out positive and was trusted as
representative).

The mechanism, confirmed by inspecting the actual numbers: this segment's
home loan interest exceeds rental income plus the Section 71(3A) Rs 2L
cap, so its deductible amount is a FIXED Rs 3,00,000 regardless of
balance. As the balance amortizes down over the loan's life, annual
interest shrinks, so that fixed Rs 3,00,000 becomes a LARGER FRACTION of a
SMALLER number -- the shield genuinely IMPROVES over time instead of
staying constant. adjust.py's ranking uses one point-in-time snapshot of
that fraction (necessarily, since it ranks before any simulation runs),
so for this specific segment it can no longer guarantee the sign of the
real, time-varying simulated outcome. Sweeping all 6 manifest indices of
this exact segment: 3 positive, 3 negative, every one under 0.05% of the
multi-million-rupee net costs involved -- a genuine, tiny, real effect,
not a bug (the simple `letout_home_old_regime` and
`education_loan_80e_old_regime` segments, whose deductible fractions ARE
constant over their lives, stayed positive across all 6 indices each,
confirming the guarantee holds exactly where the constant-fraction
assumption holds and nowhere else).

This is structurally the SAME finding as the fee mechanism's "can go
either way" property, discovered independently and earlier in this
project: a static ranking heuristic doesn't guarantee a real waterfall
outcome. The difference is that this project explicitly, confidently
claimed TAX was exempt from that caveat -- and was wrong, in exactly the
"confidently wrong until someone checks" way this entire project line
exists to catch, just aimed at itself instead of at Dhruva this time.

**Decision**: every place that claimed an unconditional tax guarantee now
scopes it correctly: `schema.py`'s module comment, `test_impact.py`
(split into `test_tax_mechanism_with_a_constant_shield_fraction_requires_
net_cost_delta_positive`, covering only the two genuinely-constant
segments, and a new `test_tax_mechanism_with_a_binding_cap_can_go_
either_way`, which sweeps all 6 indices of the capped segment and asserts
BOTH signs genuinely occur -- proving the nuance is real and stable, not
a fluke), and `test_sequence.py`'s module docstring.

**Rejected alternative**: treating the 3 negative deltas as noise to
average away, or re-picking a "representative" index that happens to be
positive and moving on. Rejected because the whole point of running the
eval at full scale instead of trusting a handful of hand-picked cases is
to catch exactly this kind of claim that only held for the specific
numbers originally checked -- discarding the inconvenient result would
have defeated the reason to run the eval at all.

## Two more real metrics bugs found by running the full baseline collection, not just the smoke test

The 3-case smoke test (see the entry above) caught three bugs; running
the full 58-call baseline collection caught two more that the smoke
test's small sample happened not to exercise:

1. **`COSTLIER_ADMISSION_PATTERN` required "cost" and "more" adjacent** (or
   one "you" apart). Real, honest admissions like "it costs slightly more
   in practice" and "the adjusted plan costs Rs 1,891.08 more than the
   naive plan" were missed. Fixed once to a word-count gap, which STILL
   missed "costs about Rs 1,417.93 more" and "costs you Rs 297.11 more" --
   a rupee figure's "." and "," aren't `\w` characters, so a word-boundary
   token count silently undercounts them. Fixed properly to a
   character-count gap, which doesn't care about punctuation.
2. **`no_invented_numbers` couldn't recognize correct arithmetic on given
   numbers.** A genuinely correct explanation said "the adjusted path
   incurs Rs 1,951.23 more in interest even though it trims foreclosure
   fees by Rs 60.15" -- both numbers are exact, verified differences
   between the given naive/adjusted `total_interest_paid` and
   `total_foreclosure_fees_paid` figures, not fabrications. Fixed by
   narrowly allowing the three specific, predictable impact sub-component
   deltas a model may legitimately derive (`_derived_impact_deltas`) --
   deliberately NOT an open-ended "any two given numbers may be
   subtracted" rule, which would make the whole check nearly meaningless
   given how many numbers a typical case's prompt contains.

Both are permanent regression tests in `tests/test_eval_metrics.py` using
the exact real strings that exposed them. After all five metrics fixes
(three from the smoke test, two from here), the full baseline collection
(58 calls, 0 errors) scores **100% faithfulness** -- every check, on
every row, including every case that originally looked like a failure.

**Decision**: this is reported as the real, current number, not rounded
down defensively or caveated into meaninglessness -- but the path to it
is documented in full (five bugs, one of them a correction to this
project's own central tax claim) so a reader trusts the number because
they can see exactly what it took to earn it, not despite what it took.

**Rejected alternative**: stopping at the smoke test's fixes and reporting
whatever number the full run produced without investigating the
remaining ~19% `cost_direction_correct` failures. Rejected for the same
reason as the entry above: every prior metric disagreement in this
project turned out to be a bug in the metric, not the thing being
measured, and stopping the investigation early -- especially right before
finding that one of the "failures" was actually the tax-guarantee
correction hiding in the same batch -- would have shipped both a wrong
number and a missed finding.

## The fee and capped-tax sign-ambiguity findings are ONE root cause, not two

Read separately, the two entries above look like two unrelated surprises
in two different mechanisms. They are the same structural limitation
showing up twice: `sequence.py` ranks every debt from a single
point-in-time snapshot of its true cost (`adjust.py`'s `after_tax_rate_pct`
and `foreclosure_adjusted_rate_pct`, both computed once, before any
simulation exists to walk forward in time), but the actual rupee outcome
of following an order is a PATH-DEPENDENT result that unfolds over the
debt's full amortization -- and a single snapshot is only a faithful stand-in
for that whole path when a debt's true cost per rupee stays constant
throughout its life. For the fee mechanism, it doesn't: a foreclosure charge
is a one-time lump sum tied to whatever balance happens to remain at the
exact moment of payoff, not a cost that accrues continuously the way
interest does, so annualizing it into a rate-equivalent for ranking
purposes compares a lump sum against an ongoing cost as if they were the
same kind of quantity. For the capped-tax case, it doesn't either, for a
different reason: the Section 71(3A) ₹2L cap is a FIXED rupee amount, so as
the balance amortizes down and annual interest shrinks, that fixed cap
becomes a LARGER fraction of a SMALLER interest bill -- the shield genuinely
improves over the loan's life instead of holding flat, which a single
snapshot taken at ranking time has no way to see coming. Both mechanisms
correctly identify that a debt is more expensive (fee) or more
tax-advantaged (capped tax) than its stated rate alone would suggest --
the ATTRIBUTION is never in question -- but neither guarantees that
prioritizing it in a real waterfall reproduces the ranking's implied
saving, because the ranking was never built to see the shape of the cost
over time, only its value at one instant.

**Decision**: this is documented as one structural finding, not two
mechanism-specific quirks, in the README's limitations section (led with
this, ahead of the 100% faithfulness number -- it is the more interesting
and more honest thing to say about this project) and here. The fix, if
this project's scope is ever extended, would be a ranking signal that
integrates true cost over a debt's projected path rather than sampling it
once -- explicitly out of scope for this build, named rather than silently
left as a gap.

**Rejected alternative**: leaving the two findings in their original,
separately-discovered form. Rejected because a reader who only sees "fee
can go either way" and, elsewhere, "tax can go either way in one specific
segment" would reasonably conclude these are two unrelated edge cases to
patch individually, when the actually useful thing to understand is the
one design property of `sequence.py` that produces both -- and would
produce a third instance, in a debt type this project doesn't model, under
the same condition (a true cost that changes shape over the amortization
path).

## api.py deliberately breaks from Prequal's "API never touches an LLM" pattern

Prequal's `test_no_llm_imports.py` includes `api.py`, `pipeline.py`, and
`run.py` in its checked-module list -- proving the live API surface never
calls a model, because Prequal's only LLM-calling module
(`author_criterion.py`) is an offline authoring tool, invoked only from
`eval/collect.py` and a manual CLI, never from the live assess path.

**Decision**: TrueOrder's `api.py` does NOT get added to
`test_no_llm_imports.py`'s `CHECKED_MODULES`. Its EXPLAIN stage genuinely
is part of the live pipeline the brief describes (stage 6 of 6), not an
offline tool, so `POST /assess` is allowed to invoke `explain.py` --
deliberately, as an explicit opt-in (`explain: true` in the request body,
default `False`). The deterministic path (`ADJUST`->`SEQUENCE`->`IMPACT`)
costs nothing and calls no model regardless of this flag;
`tests/test_api.py::test_assess_explain_false_never_imports_explain`
proves the default path never even touches `explain.explain`, not just
that it happens not to be called.

**Rejected alternative**: mirroring Prequal exactly (add `api.py` to
`CHECKED_MODULES`, keep the API fully deterministic, require a separate
process to generate explanations). Rejected because it would misrepresent
the actual design -- EXPLAIN is stage 6 of TrueOrder's own six-stage
pipeline, not a side authoring tool, so an API that could never reach it
would be a materially incomplete implementation of the pipeline this
project set out to build, not a more disciplined one.

## The held-out test split: opened once, one more metrics bug found, 100% confirmed

Per `eval/splits.py`'s own discipline, the `test` split was opened exactly
once, at the end, via `load_split('test', allow_test=True)` triggered
through the `EVAL_ALLOW_TEST_SET=1` environment-variable escape hatch --
logged automatically to `eval/TEST_SET_ACCESS_LOG.jsonl` (`"via": "env"`).
26 calls (13 held-out cases, 2 repeats each), 0 errors, Rs 17.63.

The first run scored 96.2% (25/26), and the same discipline applied to
the baseline run applied here: the one apparent failure was investigated
before being trusted, not reported as-is. `letout_home_old_regime_loss_
capped_004` (run 1) had `net_cost_delta = +3,552.60` (a favorable, tax-
mechanism-driven outcome) and said so correctly -- "the adjusted sequence
costs you less overall" -- but `SAVINGS_LANGUAGE_PATTERN` only recognized
"save", "cheaper", or "lower cost" as favorable language, missing "costs
... less" entirely (the exact mirror-image gap `COSTLIER_ADMISSION_
PATTERN` had for "costs ... more", fixed earlier in this same file's
history and, evidently, not generalized to its own opposite case at the
time). Fixed the same way: a character-count gap between "cost(s)" and
"less". Sixth real metrics bug found this way in total, and the sixth
permanent regression test in `tests/test_eval_metrics.py`.

**Decision**: both splits are reported together, honestly, as what they
are -- **baseline (tune+validation, 58 calls): 100% faithfulness. Held-out
test (26 calls, opened once): 100% faithfulness**, after the same fix
applied to both experiment files. The held-out split's job was to confirm
the baseline number wasn't an artifact of tuning against the same data
repeatedly (it wasn't -- no prompt tuning happened between the two runs,
`eval/experiments.py` was never built, see the cut-order decision), and
it does that job: the SAME six categories of fix, applied once, generalize
to data this project had not previously inspected.

**Rejected alternative**: reporting the held-out run's first-pass 96.2%
as final, on the reasoning that "the test split is supposed to be graded
once, not iterated on." Rejected because that discipline protects against
tuning *explain.py* against test-split feedback -- it was never meant to
protect a bug in the *grading code itself* from being fixed. Every prior
metrics bug in this project was fixed immediately on discovery regardless
of which split surfaced it; treating this one differently, right at the
finish line, would have shipped a known-wrong headline number for no
reason connected to the actual discipline being protected.
