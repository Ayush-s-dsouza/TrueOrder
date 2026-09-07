"""Thin FastAPI wrapper around the deterministic pipeline
(PROFILE -> ADJUST -> SEQUENCE -> IMPACT), mirroring Prequal's api.py
discipline: makes no decisions of its own, every judgment lives in the
stage that owns it.

Unlike Prequal (whose api.py/pipeline.py/run.py are checked by
test_no_llm_imports.py to prove the live API never touches an LLM, because
Prequal's only LLM-calling module is an offline authoring tool never
invoked from the live path), TrueOrder's EXPLAIN stage genuinely is part
of the live pipeline the brief describes -- so `/assess` is allowed to
invoke it, deliberately, as an explicit opt-in (`explain: true` in the
request body). Deterministic-only calls (the default) cost nothing and
call no model; requesting an explanation costs real money and takes real
time (see explain.py) and is never the silent default. api.py is
therefore NOT in test_no_llm_imports.py's CHECKED_MODULES list -- it is
an orchestration layer that intentionally exposes both the deterministic
core and the one LLM-calling stage, not part of the deterministic core
itself (see DECISIONS.md).
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from adjust import adjust_portfolio
from impact import compare_impact
from schema import AdjustedDebt, ImpactComparison, Portfolio, RepaymentOrdering
from sequence import compute_ordering

app = FastAPI(
    title="TrueOrder",
    description="Tax-and-fee-adjusted debt repayment sequencing for a mixed Indian debt portfolio.",
)


class AssessRequest(BaseModel):
    portfolio: Portfolio
    monthly_surplus: float
    explain: bool = False


class AssessResponse(BaseModel):
    adjusted_debts: list[AdjustedDebt]
    ordering: RepaymentOrdering
    impact: ImpactComparison
    explanation: Optional[str] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/assess", response_model=AssessResponse)
def assess(request: AssessRequest) -> AssessResponse:
    adjusted_debts = adjust_portfolio(request.portfolio)
    ordering = compute_ordering(request.portfolio, adjusted_debts)
    impact = compare_impact(request.portfolio, ordering, request.monthly_surplus)

    explanation = None
    if request.explain:
        from explain import explain as generate_explanation

        explanation = generate_explanation(request.portfolio, adjusted_debts, ordering, impact).text

    return AssessResponse(adjusted_debts=adjusted_debts, ordering=ordering, impact=impact, explanation=explanation)
