"""Deterministic synthetic portfolio generator, one builder function per
named segment (synth/segments.py documents why each segment exists).

Unlike Prequal's generic bureau-profile shapes (one risk shape, many
independently-sampled numeric fields), each segment here is also a specific
hand-chosen *composition* of debt types and rate relationships -- the
divergence (or, for AGREEMENT_CASE, the deliberate absence of one) each
segment demonstrates was verified by hand: every stated-rate/after-tax-rate
crossover below was computed manually against tax_rules.py/fee_rules.py
before being encoded, not just assumed to "probably" produce the right
ordering.

Jitter is intentionally conservative in this phase: `random.Random(f"{seed}:
{segment}:{index}")` (Prequal's exact string-seeding pattern) only perturbs
fields that cannot affect which debt wins a rank comparison (balances,
tenure, minimum payment) -- never the stated rates or caps whose specific
relationship to each other is what makes a segment demonstrate its labeled
divergence. Widening the jitter range for a larger synthetic eval pool is a
later-phase concern (see DECISIONS.md).
"""

from __future__ import annotations

import random

from schema import (
    AutoLoan,
    CreditCard,
    EducationLoan,
    HomeLoan,
    PersonalLoan,
    Portfolio,
    PropertyOccupancy,
    RateType,
    TaxRegime,
)


def _jitter(rng: random.Random, value: float, pct: float = 0.05) -> float:
    return round(value * (1 + rng.uniform(-pct, pct)), 2)


def _rng(seed: str, segment: str, index: int) -> random.Random:
    return random.Random(f"{seed}:{segment}:{index}")


def _build_agreement_case(seed: str, index: int) -> Portfolio:
    rng = _rng(seed, "agreement_case", index)
    return Portfolio(
        borrower_id=f"agreement_case_{index:03d}",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 80_000),
                stated_apr_pct=42.0,
                remaining_tenure_months=360,
                minimum_payment=4_000,
                current_utilisation_pct=32.0,
                aggregate_utilisation_pct=25.0,
            ),
            CreditCard(
                debt_id="cc2",
                outstanding_balance=_jitter(rng, 40_000),
                stated_apr_pct=38.0,
                remaining_tenure_months=360,
                minimum_payment=2_000,
                current_utilisation_pct=16.0,
                aggregate_utilisation_pct=25.0,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 200_000),
                stated_apr_pct=14.0,
                remaining_tenure_months=36,
                minimum_payment=7_000,
                rate_type=RateType.FLOATING,
            ),
        ],
    )


def _build_letout_home_old_regime(seed: str, index: int) -> Portfolio:
    rng = _rng(seed, "letout_home_old_regime", index)
    return Portfolio(
        borrower_id=f"letout_home_old_regime_{index:03d}",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 60_000),
                stated_apr_pct=42.0,
                remaining_tenure_months=360,
                minimum_payment=3_000,
                current_utilisation_pct=22.0,
                aggregate_utilisation_pct=22.0,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 250_000),
                stated_apr_pct=10.5,
                remaining_tenure_months=30,
                minimum_payment=9_000,
                rate_type=RateType.FLOATING,
            ),
            HomeLoan(
                debt_id="h1",
                outstanding_balance=_jitter(rng, 4_000_000),
                stated_apr_pct=11.0,
                remaining_tenure_months=180,
                minimum_payment=45_000,
                rate_type=RateType.FLOATING,
                occupancy=PropertyOccupancy.LET_OUT,
                annual_rental_income=350_000,
            ),
        ],
    )


def _build_fixed_auto_foreclosure(seed: str, index: int) -> Portfolio:
    rng = _rng(seed, "fixed_auto_foreclosure", index)
    return Portfolio(
        borrower_id=f"fixed_auto_foreclosure_{index:03d}",
        tax_regime=TaxRegime.NEW,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 50_000),
                stated_apr_pct=40.0,
                remaining_tenure_months=360,
                minimum_payment=2_500,
                current_utilisation_pct=20.0,
                aggregate_utilisation_pct=20.0,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 300_000),
                stated_apr_pct=11.0,
                remaining_tenure_months=30,
                minimum_payment=12_000,
                rate_type=RateType.FLOATING,
            ),
            AutoLoan(
                debt_id="a1",
                outstanding_balance=_jitter(rng, 400_000),
                stated_apr_pct=9.0,
                remaining_tenure_months=18,
                minimum_payment=24_000,
                rate_type=RateType.FIXED,
                foreclosure_charge_pct=4.0,
            ),
        ],
    )


def _build_utilisation_threshold(seed: str, index: int) -> Portfolio:
    rng = _rng(seed, "utilisation_threshold", index)
    return Portfolio(
        borrower_id=f"utilisation_threshold_{index:03d}",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 90_000),
                stated_apr_pct=36.0,
                remaining_tenure_months=360,
                minimum_payment=4_500,
                current_utilisation_pct=60.0,
                aggregate_utilisation_pct=34.29,
            ),
            CreditCard(
                debt_id="cc2",
                outstanding_balance=_jitter(rng, 30_000),
                stated_apr_pct=30.0,
                remaining_tenure_months=360,
                minimum_payment=1_500,
                current_utilisation_pct=15.0,
                aggregate_utilisation_pct=34.29,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 200_000),
                stated_apr_pct=32.0,
                remaining_tenure_months=24,
                minimum_payment=10_000,
                rate_type=RateType.FLOATING,
            ),
        ],
    )


def _build_selfoccupied_new_regime_regression(seed: str, index: int) -> Portfolio:
    rng = _rng(seed, "selfoccupied_new_regime_regression", index)
    return Portfolio(
        borrower_id=f"selfoccupied_new_regime_regression_{index:03d}",
        tax_regime=TaxRegime.NEW,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 60_000),
                stated_apr_pct=41.0,
                remaining_tenure_months=360,
                minimum_payment=3_000,
                current_utilisation_pct=20.0,
                aggregate_utilisation_pct=20.0,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 200_000),
                stated_apr_pct=13.0,
                remaining_tenure_months=24,
                minimum_payment=9_500,
                rate_type=RateType.FLOATING,
            ),
            HomeLoan(
                debt_id="h1",
                outstanding_balance=_jitter(rng, 3_500_000),
                stated_apr_pct=8.5,
                remaining_tenure_months=200,
                minimum_payment=32_000,
                rate_type=RateType.FLOATING,
                occupancy=PropertyOccupancy.SELF_OCCUPIED,
            ),
        ],
    )


def _build_education_loan_80e_old_regime(seed: str, index: int) -> Portfolio:
    rng = _rng(seed, "education_loan_80e_old_regime", index)
    return Portfolio(
        borrower_id=f"education_loan_80e_old_regime_{index:03d}",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 40_000),
                stated_apr_pct=39.0,
                remaining_tenure_months=360,
                minimum_payment=2_000,
                current_utilisation_pct=20.0,
                aggregate_utilisation_pct=20.0,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 150_000),
                stated_apr_pct=9.0,
                remaining_tenure_months=24,
                minimum_payment=7_000,
                rate_type=RateType.FLOATING,
            ),
            EducationLoan(
                debt_id="e1",
                outstanding_balance=_jitter(rng, 600_000),
                stated_apr_pct=11.0,
                remaining_tenure_months=72,
                minimum_payment=9_000,
                years_since_first_repayment=2,
            ),
        ],
    )


def _build_letout_home_old_regime_loss_capped(seed: str, index: int) -> Portfolio:
    """Same shape as letout_home_old_regime, but with a larger balance and
    lower rental income so remaining_loss (annual_interest - rental_offset)
    exceeds the Rs 2,00,000 Section 71(3A) cap -- the branch sample 2 never
    triggers. Balance jitter (+/-5% on ~80,00,000) keeps remaining_loss
    comfortably above the cap across the full jitter range (worst case
    ~7,36,000 loss at the low end of the range), so this doesn't depend on
    hitting an exact number.
    """
    rng = _rng(seed, "letout_home_old_regime_loss_capped", index)
    return Portfolio(
        borrower_id=f"letout_home_old_regime_loss_capped_{index:03d}",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1",
                outstanding_balance=_jitter(rng, 60_000),
                stated_apr_pct=42.0,
                remaining_tenure_months=360,
                minimum_payment=3_000,
                current_utilisation_pct=22.0,
                aggregate_utilisation_pct=22.0,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=_jitter(rng, 250_000),
                stated_apr_pct=10.5,
                remaining_tenure_months=30,
                minimum_payment=9_000,
                rate_type=RateType.FLOATING,
            ),
            HomeLoan(
                debt_id="h1",
                outstanding_balance=_jitter(rng, 8_000_000),
                stated_apr_pct=11.0,
                remaining_tenure_months=180,
                minimum_payment=85_000,
                rate_type=RateType.FLOATING,
                occupancy=PropertyOccupancy.LET_OUT,
                annual_rental_income=100_000,
            ),
        ],
    )


_BUILDERS = {
    "agreement_case": _build_agreement_case,
    "letout_home_old_regime": _build_letout_home_old_regime,
    "fixed_auto_foreclosure": _build_fixed_auto_foreclosure,
    "utilisation_threshold": _build_utilisation_threshold,
    "selfoccupied_new_regime_regression": _build_selfoccupied_new_regime_regression,
    "education_loan_80e_old_regime": _build_education_loan_80e_old_regime,
    "letout_home_old_regime_loss_capped": _build_letout_home_old_regime_loss_capped,
}


def generate_portfolio(seed: str, segment: str, index: int = 0) -> Portfolio:
    if segment not in _BUILDERS:
        raise ValueError(f"unknown segment {segment!r}, expected one of {sorted(_BUILDERS)}")
    return _BUILDERS[segment](seed, index)
