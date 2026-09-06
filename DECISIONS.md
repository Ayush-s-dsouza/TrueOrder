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

## Git repo scoped to TrueOrder/ itself

`Desktop` (the parent of `TrueOrder/`) is itself an unrelated, uncommitted
git repository containing unrelated personal files.

**Decision**: `git init` run inside `TrueOrder/` directly, giving it its
own independent history, matching Prequal's own git-scoping decision.

**Rejected alternative**: none considered -- committing TrueOrder as part
of the `Desktop` repo's history was never viable given that repo's
unrelated, pre-existing untracked contents.
