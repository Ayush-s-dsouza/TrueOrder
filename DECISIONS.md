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
