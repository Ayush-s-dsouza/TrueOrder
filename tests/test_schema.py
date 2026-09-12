"""Proves the schema's validators actually raise, not just that the happy
path builds correctly. Each test constructs an otherwise-valid debt with
one deliberate violation. A validator that silently accepted the violation
(e.g. by defaulting a missing foreclosure_charge_pct to None instead of
raising) would pass every "happy path" test in the suite while still being
wrong -- these are the tests that would catch that.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schema import (
    DivergenceMechanism,
    DivergenceRationale,
    HomeLoan,
    PersonalLoan,
    PropertyOccupancy,
    RateType,
    RepaymentOrdering,
)


def test_floating_rate_loan_rejects_a_foreclosure_charge():
    with pytest.raises(ValidationError):
        PersonalLoan(
            debt_id="p1",
            outstanding_balance=100_000,
            stated_apr_pct=12,
            remaining_tenure_months=24,
            minimum_payment=5_000,
            rate_type=RateType.FLOATING,
            foreclosure_charge_pct=2.0,
        )


def test_fixed_rate_loan_requires_a_foreclosure_charge():
    with pytest.raises(ValidationError):
        PersonalLoan(
            debt_id="p2",
            outstanding_balance=100_000,
            stated_apr_pct=12,
            remaining_tenure_months=24,
            minimum_payment=5_000,
            rate_type=RateType.FIXED,
            foreclosure_charge_pct=None,
        )


def test_let_out_home_loan_requires_rental_income():
    with pytest.raises(ValidationError):
        HomeLoan(
            debt_id="h1",
            outstanding_balance=3_000_000,
            stated_apr_pct=9,
            remaining_tenure_months=180,
            minimum_payment=30_000,
            rate_type=RateType.FLOATING,
            occupancy=PropertyOccupancy.LET_OUT,
            annual_rental_income=None,
        )


def test_self_occupied_home_loan_rejects_rental_income():
    with pytest.raises(ValidationError):
        HomeLoan(
            debt_id="h2",
            outstanding_balance=3_000_000,
            stated_apr_pct=9,
            remaining_tenure_months=180,
            minimum_payment=30_000,
            rate_type=RateType.FLOATING,
            occupancy=PropertyOccupancy.SELF_OCCUPIED,
            annual_rental_income=200_000,
        )


def test_utilisation_rationale_requires_traded_for():
    """The one mechanism that is explicitly not a cost-savings claim must
    never let that go unstated -- see DECISIONS.md's "adjusted = cheaper
    was never a valid blanket claim" entry."""
    with pytest.raises(ValidationError):
        DivergenceRationale(mechanism=DivergenceMechanism.UTILISATION, net_rupee_effect=0.0, traded_for=None)


@pytest.mark.parametrize("mechanism", [DivergenceMechanism.TAX, DivergenceMechanism.FEE])
def test_tax_and_fee_rationale_reject_traded_for(mechanism):
    """tax and fee are rupee claims on their own -- attaching a trade-off
    framing that only makes sense for utilisation would blur the exact
    distinction this validator exists to keep sharp."""
    with pytest.raises(ValidationError):
        DivergenceRationale(mechanism=mechanism, net_rupee_effect=1.0, traded_for="some trade")


def test_repayment_ordering_requires_rationale_for_every_divergence_point():
    """A divergence point with no rationale entry (or a rationale entry for
    a debt that isn't actually a divergence point) must be rejected -- a
    divergence is never left as a bare rank change with no stated reason."""
    with pytest.raises(ValidationError):
        RepaymentOrdering(
            naive_order=["a", "b"],
            adjusted_order=["b", "a"],
            divergence_points=["a", "b"],
            divergence_rationale={
                "a": DivergenceRationale(mechanism=DivergenceMechanism.TAX, net_rupee_effect=10.0)
            },
        )


def test_happy_paths_construct_without_raising():
    HomeLoan(
        debt_id="h3",
        outstanding_balance=3_000_000,
        stated_apr_pct=9,
        remaining_tenure_months=180,
        minimum_payment=30_000,
        rate_type=RateType.FLOATING,
        occupancy=PropertyOccupancy.SELF_OCCUPIED,
        annual_rental_income=None,
    )
    HomeLoan(
        debt_id="h4",
        outstanding_balance=3_000_000,
        stated_apr_pct=9,
        remaining_tenure_months=180,
        minimum_payment=30_000,
        rate_type=RateType.FIXED,
        foreclosure_charge_pct=2.5,
        occupancy=PropertyOccupancy.LET_OUT,
        annual_rental_income=200_000,
    )


def test_displaced_rationale_requires_naming_its_cause():
    """'This debt moved, for no reason of its own' is not an explanation.
    The causing debt is the only thing that makes it one, so DISPLACED
    without displaced_by must not be constructible."""
    with pytest.raises(ValidationError):
        DivergenceRationale(mechanism=DivergenceMechanism.DISPLACED, net_rupee_effect=0.0)


def test_displaced_rationale_must_have_zero_rupee_effect():
    """A displaced debt has no adjustment of its own by definition. A
    nonzero effect means it should have been attributed to its OWN
    mechanism instead -- so the two can never silently disagree."""
    with pytest.raises(ValidationError):
        DivergenceRationale(
            mechanism=DivergenceMechanism.DISPLACED, net_rupee_effect=500.0, displaced_by="h1"
        )


@pytest.mark.parametrize(
    "mechanism", [DivergenceMechanism.TAX, DivergenceMechanism.FEE, DivergenceMechanism.UTILISATION]
)
def test_non_displaced_rationales_reject_displaced_by(mechanism):
    """The mirror-image guard: a tax/fee/utilisation rationale describes
    this debt's OWN adjustment, so it must not simultaneously claim
    something else moved it."""
    kwargs = {"mechanism": mechanism, "net_rupee_effect": 1.0, "displaced_by": "h1"}
    if mechanism == DivergenceMechanism.UTILISATION:
        kwargs["traded_for"] = "credit score protection, not a rupee claim"
        kwargs["net_rupee_effect"] = 0.0
    with pytest.raises(ValidationError):
        DivergenceRationale(**kwargs)


def test_displaced_rationale_constructs_when_well_formed():
    """Positive case, so the three guards above can't pass by making
    DISPLACED unconstructible entirely."""
    rationale = DivergenceRationale(
        mechanism=DivergenceMechanism.DISPLACED, net_rupee_effect=0.0, displaced_by="h1"
    )
    assert rationale.displaced_by == "h1"
    assert rationale.traded_for is None
