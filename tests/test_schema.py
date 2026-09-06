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

from schema import HomeLoan, PersonalLoan, PropertyOccupancy, RateType


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
