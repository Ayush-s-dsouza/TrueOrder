"""SEQUENCE stage: naive (stated-APR-only) vs adjusted (true-effective-cost)
repayment order, plus the divergence between them. Zero LLM calls -- part
of the deterministic core (see tests/test_no_llm_imports.py).

The utilisation-crossing override is applied as an explicit, separate step
after cost-based sorting, not folded into effective_cost_rank_input as a
rate-equivalent number -- the heuristic isn't calibrated in interest-rate
units (see fee_rules.UTILISATION_HEURISTIC_DISCLAIMER), so representing it
as one would overstate its precision. Instead: any credit card whose
paydown would cross the 30%-aggregate-utilisation threshold is promoted
ahead of every non-crossing debt, ranked among any other crossing cards by
their own effective cost. This is a deliberate, stated design choice, not a
hidden tiebreak.
"""

from __future__ import annotations

from schema import AdjustedDebt, Portfolio, RepaymentOrdering


def naive_order(portfolio: Portfolio) -> list[str]:
    ranked = sorted(portfolio.debts, key=lambda d: (-d.stated_apr_pct, d.debt_id))
    return [d.debt_id for d in ranked]


def adjusted_order(adjusted_debts: list[AdjustedDebt]) -> list[str]:
    by_cost = sorted(
        adjusted_debts,
        key=lambda ad: (-ad.effective_cost_rank_input, ad.debt.debt_id),
    )
    crossing = [ad for ad in by_cost if ad.utilisation_priority_score > 0]
    non_crossing = [ad for ad in by_cost if ad.utilisation_priority_score <= 0]
    return [ad.debt.debt_id for ad in (crossing + non_crossing)]


def compute_ordering(portfolio: Portfolio, adjusted_debts: list[AdjustedDebt]) -> RepaymentOrdering:
    naive = naive_order(portfolio)
    adjusted = adjusted_order(adjusted_debts)
    naive_rank = {debt_id: i for i, debt_id in enumerate(naive)}
    adjusted_rank = {debt_id: i for i, debt_id in enumerate(adjusted)}
    divergence = [
        debt_id for debt_id in naive if naive_rank[debt_id] != adjusted_rank[debt_id]
    ]
    return RepaymentOrdering(
        naive_order=naive,
        adjusted_order=adjusted,
        divergence_points=divergence,
    )
