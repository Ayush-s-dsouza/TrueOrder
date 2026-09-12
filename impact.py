"""IMPACT stage: what a repayment order actually costs, simulated month by
month with a real waterfall -- surplus cascades to the next active debt the
same month a higher-priority one is paid off, rather than a naive bug that
would keep dumping money into an already-finished debt. Zero LLM calls --
part of the deterministic core (see tests/test_no_llm_imports.py).

Interest accrues at each debt's STATED rate every month -- that is what a
lender actually charges, regardless of any tax/fee adjustment used for
ranking in adjust.py/sequence.py. The tax and foreclosure adjustments show
up here instead as real, dated rupee amounts: a foreclosure fee is charged
once, when a fixed-rate loan is paid off before its originally stated
remaining tenure, on the outstanding balance (including that month's
accrued interest) immediately before the payoff payment -- a documented
approximation of "the amount being foreclosed," since lenders vary in
whether the fee base includes that final month's interest. A tax benefit is
realized once per simulated year, computed from the ACTUAL interest accrued
on that debt during that year (a more accurate figure than adjust.py's flat
balance-times-rate approximation, which exists there only because ADJUST
needs a single before-the-fact number to rank debts before any simulation
has run -- this is a deliberate, documented difference between the two
stages, not an inconsistency).

IMPORTANT, verified empirically against the checkpoint samples (see
DECISIONS.md): the adjusted order is NOT always net_cost-cheaper than the
naive one. For a tax-driven divergence it reliably is, because the tax
benefit is a continuous, ongoing percentage of actual accrued interest --
the same "weighted balance over time" structure as the interest cost it
discounts, so ranking by after-tax rate aligns with minimizing net cost.
For a fee-driven divergence, it can go the other way: a foreclosure charge
is a one-time cost proportional to whatever balance remains at the moment
of payoff, not a continuous rate, so promoting a genuinely-lower-nominal-
rate debt ahead of a genuinely-higher-nominal-rate one (because the
lower-rate debt's fee-annualized ranking number looks worse) can increase
total nominal interest by more than the one-time fee saves. And for the
utilisation-heuristic divergence, net_cost is EXPECTED to be slightly worse
for the adjusted order, because that heuristic protects a credit score, not
rupees -- it was never a cost-minimization signal to begin with. This
module reports what actually happens; it does not force the ADJUST/SEQUENCE
stages' ranking to agree with it after the fact.
"""

from __future__ import annotations

import fee_rules
import tax_rules
from schema import (
    AutoLoan,
    Debt,
    EducationLoan,
    HomeLoan,
    ImpactComparison,
    ImpactResult,
    PersonalLoan,
    Portfolio,
    RateType,
    RepaymentOrdering,
)

MAX_SIMULATION_MONTHS = 600  # 50 years -- a safety cap against a misconfigured surplus, not a realistic expectation


def _is_fixed_rate_loan(debt: Debt) -> bool:
    return isinstance(debt, (PersonalLoan, AutoLoan, HomeLoan)) and debt.rate_type == RateType.FIXED


def _annual_tax_benefit(debt: Debt, portfolio: Portfolio, year_interest: float, years_elapsed: int) -> float:
    """`year_interest` is the ACTUAL interest accrued on this debt during
    the (possibly partial, if paid off mid-year) simulated year.
    `years_elapsed` counts how many full simulated years have already
    passed for this debt, used only to advance an education loan's 8-year
    window -- a home loan's deduction has no such window."""
    if isinstance(debt, HomeLoan):
        result = tax_rules.home_loan_deduction(
            regime=portfolio.tax_regime.value,
            occupancy=debt.occupancy.value,
            annual_interest=year_interest,
            annual_rental_income=debt.annual_rental_income,
        )
        return result.deductible_amount * (portfolio.marginal_tax_rate_pct / 100)

    if isinstance(debt, EducationLoan):
        result = tax_rules.education_loan_deduction(
            regime=portfolio.tax_regime.value,
            annual_interest=year_interest,
            years_since_first_repayment=debt.years_since_first_repayment + years_elapsed,
        )
        return result.deductible_amount * (portfolio.marginal_tax_rate_pct / 100)

    return 0.0


def simulate_waterfall(portfolio: Portfolio, order: list[str], monthly_surplus: float) -> ImpactResult:
    """`monthly_surplus` is capacity ON TOP OF the sum of every debt's own
    minimum payment -- the borrower's total fixed monthly debt-service
    budget is `sum(all original minimums) + monthly_surplus`, held constant
    for the life of the simulation. This is the "real waterfall" the
    surplus-only version of this function got wrong: once a debt is paid
    off, its minimum payment is no longer owed, so that capacity must roll
    forward into the surplus available to the next-priority debt -- the
    classic "snowball" effect. A version that keeps `monthly_surplus` fixed
    forever and lets a finished debt's minimum simply stop being paid
    (rather than being redirected) silently shrinks the total budget every
    time a debt clears, which then makes ANY order that clears the smaller
    balances later look artificially cheaper -- exactly backwards from what
    this stage exists to measure. `total_monthly_capacity - (sum of
    minimums still owed by active debts)` recomputes the true surplus fresh
    every month, so it grows automatically as debts clear.
    """
    debts_by_id = {d.debt_id: d for d in portfolio.debts}
    balances = {d.debt_id: d.outstanding_balance for d in portfolio.debts}
    monthly_rates = {d.debt_id: d.stated_apr_pct / 1200 for d in portfolio.debts}
    total_monthly_capacity = sum(d.minimum_payment for d in portfolio.debts) + monthly_surplus

    total_interest_paid = 0.0
    total_foreclosure_fees_paid = 0.0
    total_tax_benefit_realized = 0.0

    year_interest_accum = {d.debt_id: 0.0 for d in portfolio.debts}
    years_elapsed = {d.debt_id: 0 for d in portfolio.debts}

    active = set(balances)
    month = 0

    while active:
        month += 1
        if month > MAX_SIMULATION_MONTHS:
            raise RuntimeError(
                f"waterfall did not pay off all debts within {MAX_SIMULATION_MONTHS} months -- "
                f"monthly_surplus ({monthly_surplus}) is too small relative to this portfolio's "
                f"balances and minimum payments"
            )

        pre_payment_balance: dict[str, float] = {}
        for debt_id in active:
            interest = balances[debt_id] * monthly_rates[debt_id]
            balances[debt_id] += interest
            total_interest_paid += interest
            year_interest_accum[debt_id] += interest
            pre_payment_balance[debt_id] = balances[debt_id]

        for debt_id in active:
            payment = min(debts_by_id[debt_id].minimum_payment, balances[debt_id])
            balances[debt_id] -= payment

        active_minimums_sum = sum(debts_by_id[debt_id].minimum_payment for debt_id in active)
        remaining_surplus = total_monthly_capacity - active_minimums_sum
        for debt_id in [d for d in order if d in active]:
            if remaining_surplus <= 0:
                break
            payment = min(remaining_surplus, balances[debt_id])
            balances[debt_id] -= payment
            remaining_surplus -= payment

        newly_paid_off = [debt_id for debt_id in active if balances[debt_id] <= 1e-6]
        for debt_id in newly_paid_off:
            balances[debt_id] = 0.0
            debt = debts_by_id[debt_id]

            # "Foreclosed early" means retired sooner than this loan would
            # have been on its minimum payment alone -- the same derived
            # horizon fee_rules/adjust.py annualize the charge over, so the
            # two stages cannot disagree about whether a fee is incurred.
            # Previously this keyed off `remaining_tenure_months`, a stated
            # field with no schema constraint tying it to the loan's actual
            # cash flows, which made the stages contradict each other
            # systematically at short stated tenures (see DECISIONS.md).
            if _is_fixed_rate_loan(debt):
                natural_months = fee_rules.natural_payoff_months(
                    outstanding_balance=debt.outstanding_balance,
                    stated_apr_pct=debt.stated_apr_pct,
                    minimum_payment=debt.minimum_payment,
                )
                foreclosed_early = natural_months is None or month < natural_months
                if foreclosed_early:
                    total_foreclosure_fees_paid += pre_payment_balance[debt_id] * (debt.foreclosure_charge_pct / 100)

            if isinstance(debt, (HomeLoan, EducationLoan)):
                total_tax_benefit_realized += _annual_tax_benefit(
                    debt, portfolio, year_interest_accum[debt_id], years_elapsed[debt_id]
                )

            active.discard(debt_id)

        if month % 12 == 0:
            for debt_id in list(active):
                debt = debts_by_id[debt_id]
                if isinstance(debt, (HomeLoan, EducationLoan)):
                    total_tax_benefit_realized += _annual_tax_benefit(
                        debt, portfolio, year_interest_accum[debt_id], years_elapsed[debt_id]
                    )
                year_interest_accum[debt_id] = 0.0
                years_elapsed[debt_id] += 1

    net_cost = total_interest_paid + total_foreclosure_fees_paid - total_tax_benefit_realized
    return ImpactResult(
        total_interest_paid=total_interest_paid,
        total_foreclosure_fees_paid=total_foreclosure_fees_paid,
        total_tax_benefit_realized=total_tax_benefit_realized,
        net_cost=net_cost,
        months_to_payoff=month,
    )


def compare_impact(portfolio: Portfolio, ordering: RepaymentOrdering, monthly_surplus: float) -> ImpactComparison:
    naive = simulate_waterfall(portfolio, ordering.naive_order, monthly_surplus)
    adjusted = simulate_waterfall(portfolio, ordering.adjusted_order, monthly_surplus)
    return ImpactComparison(naive=naive, adjusted=adjusted, net_cost_delta=naive.net_cost - adjusted.net_cost)
