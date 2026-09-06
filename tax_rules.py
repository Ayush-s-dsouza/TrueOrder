"""Verified Indian income-tax rules for debt-interest deductions, as they
apply to the two debt types with a real tax dimension: home loans (Section
24(b)) and education loans (Section 80E). Every rule below was verified via
web search on 2026-09-06, current as of that date and subject to change in a
future Finance Act.

Zero LLM calls, zero imports beyond stdlib -- this module is part of the
deterministic core (see tests/test_no_llm_imports.py). It exposes pure
functions only; schema.py's models are not imported here to keep this module
independently testable and free of any circular-import risk.

CORRECTIONS MADE DURING RESEARCH (see DECISIONS.md for the full story):
the project brief originally assumed Section 80E applies "regardless of
regime." That is false -- Section 80E is unavailable under the new regime.
Both this module's behaviour and tests/test_tax_rules.py's regression tests
encode the corrected, verified rule, not the original assumption.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Section 24(b) -- home loan interest deduction
#
# Old regime + self-occupied: deduction capped at Rs 2,00,000/year.
# Old regime + let-out: full interest deductible against rental income; any
#   resulting loss set off against other income capped at Rs 2,00,000/year
#   (Section 71(3A)), excess carried forward 8 years (not modeled here --
#   this module computes the CURRENT YEAR deductible amount only).
# New regime + self-occupied: deduction fully blocked. No exceptions.
# New regime + let-out: full interest still deductible against rental
#   income (Section 24(b) itself is not blocked for let-out property in the
#   new regime), but a resulting loss has NO inter-head set-off at all --
#   Section 115BAC blocks it entirely (old regime's Rs 2L set-off allowance
#   does not carry over). Only carry-forward against future house-property
#   income is available, which this module does not model as a current-year
#   benefit.
#
# Sources (verified 2026-09-06):
#   https://www.bajajfinserv.in/tax-deduction-on-home-loan-interest-under-section-24
#   https://www.kotaklife.com/insurance-guide/savingstax/section-24-in-new-tax-regime
#   https://www.taxbuddy.com/blog/house-property-loss-set-off  (Sec 71(3A), AY 2025-26)
#   https://www.patronaccounting.com/blog/house-property-loss-set-off-rs-2-lakh-cap-old-regime
# ---------------------------------------------------------------------------

SELF_OCCUPIED_DEDUCTION_CAP_OLD_REGIME = 200_000.0
LET_OUT_LOSS_SETOFF_CAP_OLD_REGIME = 200_000.0

EDUCATION_LOAN_80E_WINDOW_YEARS = 8


@dataclass(frozen=True)
class DeductionResult:
    """The amount of interest that is actually deductible this year, plus a
    note that must always explain the outcome -- including the "no
    deduction applies" outcome, which is never left blank."""

    deductible_amount: float
    note: str


def home_loan_deduction(
    *,
    regime: str,
    occupancy: str,
    annual_interest: float,
    annual_rental_income: float | None,
) -> DeductionResult:
    """Section 24(b). `regime` is "old" or "new"; `occupancy` is
    "self_occupied" or "let_out". `annual_rental_income` must be provided
    (non-None) iff occupancy is "let_out" -- schema.py enforces this at the
    data-model level; this function trusts that invariant and does not
    re-validate it, since re-validating here would just be a second place
    for the same rule to drift out of sync.
    """
    if occupancy == "self_occupied":
        if regime == "old":
            deductible = min(annual_interest, SELF_OCCUPIED_DEDUCTION_CAP_OLD_REGIME)
            return DeductionResult(
                deductible_amount=deductible,
                note=(
                    f"Section 24(b), old regime, self-occupied: interest deductible "
                    f"up to Rs {SELF_OCCUPIED_DEDUCTION_CAP_OLD_REGIME:,.0f}/year. "
                    f"Deductible amount this year: Rs {deductible:,.0f}."
                ),
            )
        # regime == "new"
        return DeductionResult(
            deductible_amount=0.0,
            note=(
                "Section 24(b) deduction is fully blocked for a self-occupied "
                "property under the new tax regime (Section 115BAC) -- no "
                "exceptions. No deduction applies."
            ),
        )

    # occupancy == "let_out"
    assert annual_rental_income is not None, (
        "let_out home loan must carry annual_rental_income -- schema.py should "
        "have rejected this input before it reached tax_rules.py"
    )
    rental_offset = min(annual_interest, annual_rental_income)
    remaining_loss = annual_interest - rental_offset

    if regime == "old":
        loss_setoff = min(remaining_loss, LET_OUT_LOSS_SETOFF_CAP_OLD_REGIME)
        deductible = rental_offset + loss_setoff
        return DeductionResult(
            deductible_amount=deductible,
            note=(
                f"Section 24(b), old regime, let-out: Rs {rental_offset:,.0f} "
                f"deducted against rental income (uncapped), plus Rs {loss_setoff:,.0f} "
                f"of the resulting loss set off against other income under Section "
                f"71(3A) (capped at Rs {LET_OUT_LOSS_SETOFF_CAP_OLD_REGIME:,.0f}/year). "
                f"Deductible amount this year: Rs {deductible:,.0f}."
            ),
        )

    # regime == "new"
    return DeductionResult(
        deductible_amount=rental_offset,
        note=(
            f"Section 24(b), new regime, let-out: Rs {rental_offset:,.0f} deducted "
            f"against rental income (uncapped, still allowed for let-out under the "
            f"new regime). The remaining Rs {remaining_loss:,.0f} of interest cannot "
            f"be set off against other income at all under the new regime (Section "
            f"115BAC blocks inter-head set-off entirely) -- only carried forward "
            f"against future house-property income, which is not counted as a "
            f"current-year benefit here. Deductible amount this year: "
            f"Rs {rental_offset:,.0f}."
        ),
    )


# ---------------------------------------------------------------------------
# Section 80E -- education loan interest deduction
#
# Old regime only. Uncapped amount, interest-only (no principal deduction),
# available for 8 consecutive assessment years starting the year repayment
# begins, or until the interest is fully repaid, whichever is earlier. NOT
# available under the new regime at all -- this corrects the project
# brief's original "regardless of regime" assumption (see DECISIONS.md).
#
# Sources (verified 2026-09-06):
#   https://www.taxbuddy.com/blog/maximum-deduction-under-section-80e
#   https://taxgarden.in/blog/section-80e-education-loan-interest-deduction-ay-2026-27
# ---------------------------------------------------------------------------


def education_loan_deduction(
    *,
    regime: str,
    annual_interest: float,
    years_since_first_repayment: int,
) -> DeductionResult:
    if regime == "new":
        return DeductionResult(
            deductible_amount=0.0,
            note=(
                "Section 80E is not available under the new tax regime at all "
                "(Section 115BAC's permitted-deductions list excludes it). No "
                "deduction applies."
            ),
        )

    if years_since_first_repayment >= EDUCATION_LOAN_80E_WINDOW_YEARS:
        return DeductionResult(
            deductible_amount=0.0,
            note=(
                f"Section 80E's {EDUCATION_LOAN_80E_WINDOW_YEARS}-year window "
                f"(from the year repayment began) has lapsed -- this is year "
                f"{years_since_first_repayment + 1} of repayment. No deduction "
                f"applies."
            ),
        )

    return DeductionResult(
        deductible_amount=annual_interest,
        note=(
            f"Section 80E, old regime, year {years_since_first_repayment + 1} of "
            f"{EDUCATION_LOAN_80E_WINDOW_YEARS}: full interest deductible, "
            f"uncapped, interest-only (no principal deduction). Deductible amount "
            f"this year: Rs {annual_interest:,.0f}."
        ),
    )


# ---------------------------------------------------------------------------
# Shared: turn a deductible amount into an after-tax effective rate.
#
# effective_rate = stated_rate * (1 - marginal_tax_rate * deductible_fraction)
# where deductible_fraction = deductible_amount / annual_interest. This
# scales linearly between "no deduction" (fraction 0, rate unchanged) and
# "full deduction" (fraction 1, rate reduced by the full marginal-rate
# shield) -- it is an approximation that treats annual_interest as constant
# across the year (outstanding_balance * stated_rate), which is standard for
# a comparative ranking use case like this one, not a full month-by-month
# amortization (that level of precision belongs to impact.py's waterfall).
# ---------------------------------------------------------------------------


def after_tax_rate(
    *, stated_rate_pct: float, deductible_amount: float, annual_interest: float, marginal_tax_rate_pct: float
) -> float:
    if annual_interest <= 0:
        return stated_rate_pct
    deductible_fraction = deductible_amount / annual_interest
    return stated_rate_pct * (1 - (marginal_tax_rate_pct / 100) * deductible_fraction)
