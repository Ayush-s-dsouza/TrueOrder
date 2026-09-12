"""Required regression tests -- each one is a named, permanent guard against
a specific wrong assumption that was actually made (and caught) during this
project's own research. Every test asserts BOTH that after_tax_rate_pct
equals stated_apr_pct (the deduction is truly zero, not just small) AND
that the note explicitly names why -- an empty/generic note would be
indistinguishable from a rule that was never checked at all.

Proving a deduction activates correctly without also proving it deactivates
correctly under every input that should turn it off is an asymmetric-
testing gap -- these three tests exist specifically to close it (see
DECISIONS.md and tests/test_schema.py's validator tests, which close the
equivalent gap on the fee-rule side).
"""

from __future__ import annotations

import re

import pytest

import tax_rules
from adjust import _annual_interest, adjust_portfolio
from schema import EducationLoan, HomeLoan, Portfolio, PropertyOccupancy, RateType, TaxRegime
from synth.generator import generate_portfolio

SEED = "trueorder-checkpoint-2026-09-06"


def _only_debt_adjustment(portfolio: Portfolio):
    [adjusted] = adjust_portfolio(portfolio)
    return adjusted


def test_self_occupied_home_loan_under_new_regime_has_zero_tax_adjustment():
    """The regression for the brief's ORIGINAL wrong assumption: Section
    24(b) is fully blocked for a self-occupied property under the new
    regime, no exceptions."""
    portfolio = Portfolio(
        borrower_id="regression_self_occupied_new_regime",
        tax_regime=TaxRegime.NEW,
        marginal_tax_rate_pct=30.0,
        debts=[
            HomeLoan(
                debt_id="h1",
                outstanding_balance=3_500_000,
                stated_apr_pct=8.5,
                remaining_tenure_months=200,
                minimum_payment=32_000,
                rate_type=RateType.FLOATING,
                occupancy=PropertyOccupancy.SELF_OCCUPIED,
            )
        ],
    )
    adjusted = _only_debt_adjustment(portfolio)
    assert adjusted.after_tax_rate_pct == adjusted.debt.stated_apr_pct
    assert "new tax regime" in adjusted.tax_adjustment_note.lower()
    assert "blocked" in adjusted.tax_adjustment_note.lower()


def test_education_loan_past_its_8_year_80e_window_has_zero_tax_adjustment():
    """The regression for the RESEARCH-CORRECTED wrong assumption: the
    brief originally assumed Section 80E applies 'regardless of regime'
    and made no mention of the 8-year window turning off -- this proves the
    window's off-switch, independent of regime."""
    portfolio = Portfolio(
        borrower_id="regression_education_loan_window_lapsed",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            EducationLoan(
                debt_id="e1",
                outstanding_balance=600_000,
                stated_apr_pct=11.0,
                remaining_tenure_months=24,
                minimum_payment=9_000,
                years_since_first_repayment=8,
            )
        ],
    )
    adjusted = _only_debt_adjustment(portfolio)
    assert adjusted.after_tax_rate_pct == adjusted.debt.stated_apr_pct
    assert "8-year" in adjusted.tax_adjustment_note or "lapsed" in adjusted.tax_adjustment_note.lower()


def test_education_loan_under_new_regime_has_zero_tax_adjustment():
    """The regression for the RESEARCH-CORRECTED wrong assumption, other
    half: Section 80E is unavailable under the new regime at all, even
    well within the 8-year window."""
    portfolio = Portfolio(
        borrower_id="regression_education_loan_new_regime",
        tax_regime=TaxRegime.NEW,
        marginal_tax_rate_pct=30.0,
        debts=[
            EducationLoan(
                debt_id="e1",
                outstanding_balance=600_000,
                stated_apr_pct=11.0,
                remaining_tenure_months=72,
                minimum_payment=9_000,
                years_since_first_repayment=2,
            )
        ],
    )
    adjusted = _only_debt_adjustment(portfolio)
    assert adjusted.after_tax_rate_pct == adjusted.debt.stated_apr_pct
    assert "new tax regime" in adjusted.tax_adjustment_note.lower()
    assert "80e" in adjusted.tax_adjustment_note.lower() or "115bac" in adjusted.tax_adjustment_note.lower()


def test_education_loan_inside_window_under_old_regime_does_get_a_deduction():
    """The mirror-image sanity check: same loan, same regime, but still
    inside the window -- must NOT be zero. Without this, the two 'off'
    tests above could both trivially pass if education_loan_deduction()
    were broken to always return zero."""
    portfolio = Portfolio(
        borrower_id="sanity_education_loan_active",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            EducationLoan(
                debt_id="e1",
                outstanding_balance=600_000,
                stated_apr_pct=11.0,
                remaining_tenure_months=72,
                minimum_payment=9_000,
                years_since_first_repayment=2,
            )
        ],
    )
    adjusted = _only_debt_adjustment(portfolio)
    assert adjusted.after_tax_rate_pct < adjusted.debt.stated_apr_pct
    assert abs(adjusted.after_tax_rate_pct - 11.0 * 0.7) < 1e-9


def test_letout_home_loan_with_loss_over_2l_cap_carries_forward_the_excess():
    """Sample 2 (letout_home_old_regime) defines the Section 71(3A) Rs 2L
    set-off cap but never triggers it -- its remaining_loss (interest minus
    rental income) stays under the cap, so 100% of interest ends up
    deductible anyway. This is the one branch that actually exercises the
    cap: a larger balance / lower rental income pushes remaining_loss above
    Rs 2,00,000, so only part of it can be set off this year and the rest
    must carry forward (not counted as a current-year benefit, per
    tax_rules.py's docstring)."""
    portfolio = generate_portfolio(SEED, "letout_home_old_regime_loss_capped", index=0)
    [home_loan] = [d for d in portfolio.debts if isinstance(d, HomeLoan)]

    annual_interest = _annual_interest(home_loan)
    result = tax_rules.home_loan_deduction(
        regime=portfolio.tax_regime.value,
        occupancy=home_loan.occupancy.value,
        annual_interest=annual_interest,
        annual_rental_income=home_loan.annual_rental_income,
    )

    # Absorption capacity is the POST-Section-24(a) figure (0.70 x NAV), not
    # gross rent -- mirroring tax_rules.py. Reconstructing it from gross rent
    # here would still satisfy the assertions below (the term cancels), but
    # would quietly document a calculation the code no longer performs.
    net_rental_income = home_loan.annual_rental_income * (1 - tax_rules.LET_OUT_STANDARD_DEDUCTION_RATE)
    rental_offset = min(annual_interest, net_rental_income)
    remaining_loss = annual_interest - rental_offset
    carried_forward = remaining_loss - (result.deductible_amount - rental_offset)
    deductible_fraction = result.deductible_amount / annual_interest

    assert remaining_loss > 200_000, "test setup must actually exceed the cap"
    assert deductible_fraction < 1.0
    assert carried_forward > 0
    assert carried_forward == pytest.approx(annual_interest - result.deductible_amount)


def test_sample_7_note_states_the_post_24a_deductible_and_cites_24a():
    """Guards a specific class of drift: correct numeric fields sitting next
    to stale prose reasoning. When Section 24(a) was added, sample 7's
    deductible moved Rs 300,000 -> Rs 270,000; a note still saying
    "Rs 300,000", or still explaining the result purely via 24(b)/71(3A)
    with no mention of the standard deduction that actually drove it, would
    be just as wrong as a wrong number -- and far harder to notice, since
    every numeric assertion in the suite would still pass.

    Pinned to sample 7 specifically because it is the one committed sample
    where the Rs 2L cap binds, which is the only regime in which 24(a)
    changes the answer at all."""
    portfolio = generate_portfolio(SEED, "letout_home_old_regime_loss_capped", index=0)
    [home_loan_adjusted] = [
        ad for ad in adjust_portfolio(portfolio) if ad.debt.debt_id == "h1"
    ]
    note = home_loan_adjusted.tax_adjustment_note

    assert "270,000" in note, f"note does not state the post-24(a) deductible: {note}"
    assert "300,000" not in note, f"note still states the pre-24(a) deductible: {note}"
    assert "24(a)" in note, f"note does not cite Section 24(a): {note}"
    assert "30% standard deduction" in note, f"note does not explain the 30% standard deduction: {note}"


@pytest.mark.parametrize(
    "regime,occupancy,rental,interest",
    [
        ("old", "let_out", 100_000.0, 800_000.0),   # cap binds
        ("old", "let_out", 350_000.0, 426_828.0),   # cap does not bind
        ("new", "let_out", 100_000.0, 800_000.0),   # no inter-head set-off
        ("old", "self_occupied", None, 800_000.0),  # flat Rs 2L cap
        ("new", "self_occupied", None, 800_000.0),  # fully blocked
    ],
)
def test_every_note_agrees_with_its_own_deductible_amount(regime, occupancy, rental, interest):
    """The general invariant behind the sample-7 test above: a note either
    states a deductible figure that MATCHES the numeric field beside it, or
    says no deduction applies and the field is zero. Nothing in between.

    This is what actually makes prose/number drift impossible to reintroduce
    quietly -- a future edit that changes the calculation but not the note
    (or vice versa) fails here regardless of which specific values are
    involved, without anyone having to remember to update a hardcoded
    expectation."""
    result = tax_rules.home_loan_deduction(
        regime=regime, occupancy=occupancy, annual_interest=interest, annual_rental_income=rental
    )
    stated = re.search(r"Deductible amount this year: Rs ([\d,]+)", result.note)

    if stated is None:
        assert result.deductible_amount == 0.0, (
            f"note states no deductible figure but deductible_amount is "
            f"{result.deductible_amount}: {result.note}"
        )
        assert "No deduction applies" in result.note
    else:
        assert float(stated.group(1).replace(",", "")) == pytest.approx(
            result.deductible_amount, abs=1.0
        ), f"note says Rs {stated.group(1)} but deductible_amount is {result.deductible_amount}"
