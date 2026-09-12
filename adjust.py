"""ADJUST stage: turn each debt's stated APR into its true effective cost --
an after-tax rate (tax_rules.py), a foreclosure-adjusted rate (fee_rules.py),
and, for credit cards, a utilisation-crossing priority score. Zero LLM
calls -- part of the deterministic core (see tests/test_no_llm_imports.py).

The tax-shield discount and the foreclosure-charge surcharge are computed as
independent deltas from the *stated* rate and then combined, rather than
one adjustment compounding on top of the other's already-adjusted rate --
they are independent phenomena (a tax authority's treatment of interest has
nothing to do with a lender's prepayment terms), and compounding them would
make the size of one adjustment depend on the order they happen to be
applied in, which has no principled basis here.
"""

from __future__ import annotations

import fee_rules
import tax_rules
from schema import (
    AdjustedDebt,
    AutoLoan,
    CreditCard,
    Debt,
    EducationLoan,
    HomeLoan,
    PersonalLoan,
    Portfolio,
)


def _annual_interest(debt: Debt) -> float:
    return debt.outstanding_balance * (debt.stated_apr_pct / 100)


def _tax_adjustment(debt: Debt, portfolio: Portfolio) -> tuple[float, str]:
    """Returns (after_tax_rate_pct, note). Only home loans (Section 24(b))
    and education loans (Section 80E) have a tax dimension in this model --
    every other debt type gets an explicit "no adjustment" note, never a
    silently-omitted one."""
    annual_interest = _annual_interest(debt)

    if isinstance(debt, HomeLoan):
        result = tax_rules.home_loan_deduction(
            regime=portfolio.tax_regime.value,
            occupancy=debt.occupancy.value,
            annual_interest=annual_interest,
            annual_rental_income=debt.annual_rental_income,
        )
        rate = tax_rules.after_tax_rate(
            stated_rate_pct=debt.stated_apr_pct,
            deductible_amount=result.deductible_amount,
            annual_interest=annual_interest,
            marginal_tax_rate_pct=portfolio.marginal_tax_rate_pct,
        )
        return rate, result.note

    if isinstance(debt, EducationLoan):
        result = tax_rules.education_loan_deduction(
            regime=portfolio.tax_regime.value,
            annual_interest=annual_interest,
            years_since_first_repayment=debt.years_since_first_repayment,
        )
        rate = tax_rules.after_tax_rate(
            stated_rate_pct=debt.stated_apr_pct,
            deductible_amount=result.deductible_amount,
            annual_interest=annual_interest,
            marginal_tax_rate_pct=portfolio.marginal_tax_rate_pct,
        )
        return rate, result.note

    return (
        debt.stated_apr_pct,
        "No tax deduction applies: only home loan interest (Section 24(b)) and "
        "education loan interest (Section 80E) have a tax dimension in this "
        "model; this debt type has neither.",
    )


def _fee_adjustment(debt: Debt) -> tuple[float, str]:
    """Returns (foreclosure_adjusted_rate_pct, note)."""
    if isinstance(debt, CreditCard):
        result = fee_rules.credit_card_foreclosure_note(stated_rate_pct=debt.stated_apr_pct)
        return result.foreclosure_adjusted_rate_pct, result.note

    if isinstance(debt, (HomeLoan, AutoLoan, PersonalLoan)):
        result = fee_rules.loan_foreclosure_adjustment(
            rate_type=debt.rate_type.value,
            stated_rate_pct=debt.stated_apr_pct,
            foreclosure_charge_pct=debt.foreclosure_charge_pct,
            outstanding_balance=debt.outstanding_balance,
            minimum_payment=debt.minimum_payment,
        )
        return result.foreclosure_adjusted_rate_pct, result.note

    # EducationLoan
    return (
        debt.stated_apr_pct,
        "Foreclosure-charge modeling is out of scope for education loans in "
        "this project; only the Section 80E tax dimension is modeled for this "
        "debt type (see DECISIONS.md).",
    )


def _utilisation_priority_scores(cards: list[CreditCard]) -> dict[str, float]:
    """A card gets priority score 1.0 if paying off its balance alone would
    move the portfolio's aggregate utilisation from above the 30% threshold
    to at-or-below it; 0.0 otherwise (including when the portfolio is
    already at or below the threshold, in which case no card gets a
    crossing bonus). Binary, not continuous -- this is a heuristic override
    signal, not a calibrated score (see fee_rules.UTILISATION_HEURISTIC_DISCLAIMER)."""
    if not cards:
        return {}

    aggregate_pct = cards[0].aggregate_utilisation_pct  # validated equal across all cards
    total_balance = sum(c.outstanding_balance for c in cards)
    total_limit = total_balance / (aggregate_pct / 100)

    scores: dict[str, float] = {}
    for card in cards:
        if aggregate_pct <= fee_rules.UTILISATION_THRESHOLD_PCT:
            scores[card.debt_id] = 0.0
            continue
        remaining_balance = total_balance - card.outstanding_balance
        new_aggregate_pct = (remaining_balance / total_limit) * 100
        scores[card.debt_id] = 1.0 if new_aggregate_pct <= fee_rules.UTILISATION_THRESHOLD_PCT else 0.0
    return scores


def adjust_portfolio(portfolio: Portfolio) -> list[AdjustedDebt]:
    cards = [d for d in portfolio.debts if isinstance(d, CreditCard)]
    utilisation_scores = _utilisation_priority_scores(cards)

    adjusted: list[AdjustedDebt] = []
    for debt in portfolio.debts:
        after_tax_rate_pct, tax_note = _tax_adjustment(debt, portfolio)
        foreclosure_adjusted_rate_pct, fee_note = _fee_adjustment(debt)
        utilisation_score = utilisation_scores.get(debt.debt_id, 0.0)

        # Independent deltas from the stated rate, combined -- see module
        # docstring for why this is additive rather than compounding.
        tax_delta = after_tax_rate_pct - debt.stated_apr_pct
        fee_delta = foreclosure_adjusted_rate_pct - debt.stated_apr_pct
        effective_cost_rank_input = debt.stated_apr_pct + tax_delta + fee_delta

        adjusted.append(
            AdjustedDebt(
                debt=debt,
                after_tax_rate_pct=after_tax_rate_pct,
                tax_adjustment_note=tax_note,
                foreclosure_adjusted_rate_pct=foreclosure_adjusted_rate_pct,
                fee_adjustment_note=fee_note,
                utilisation_priority_score=utilisation_score,
                effective_cost_rank_input=effective_cost_rank_input,
            )
        )
    return adjusted
