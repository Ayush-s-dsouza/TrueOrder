"""Regenerates one manifest case's full ground truth (Portfolio,
AdjustedDebts, RepaymentOrdering, ImpactComparison) from its stored
portfolio JSON. Shared by collect.py and metrics.py so there is exactly
one place this reconstruction happens -- not two copies that could drift
apart. Zero LLM calls; the manifest stores only the portfolio, never the
derived ground truth, so this is the single source of truth for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from adjust import adjust_portfolio
from impact import compare_impact
from schema import AdjustedDebt, ImpactComparison, Portfolio, RepaymentOrdering
from sequence import compute_ordering


@dataclass(frozen=True)
class CaseGroundTruth:
    portfolio: Portfolio
    adjusted_debts: list[AdjustedDebt]
    ordering: RepaymentOrdering
    impact: ImpactComparison


def ground_truth_for_case(case: dict) -> CaseGroundTruth:
    portfolio = Portfolio.model_validate(case["portfolio"])
    adjusted_debts = adjust_portfolio(portfolio)
    ordering = compute_ordering(portfolio, adjusted_debts)
    impact = compare_impact(portfolio, ordering, case["monthly_surplus"])
    return CaseGroundTruth(portfolio=portfolio, adjusted_debts=adjusted_debts, ordering=ordering, impact=impact)
