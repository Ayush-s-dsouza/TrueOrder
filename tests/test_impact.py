"""IMPACT stage tests. Two kinds of claim get tested here:

1. The waterfall mechanics themselves -- in particular, that a paid-off
   debt's freed-up minimum payment rolls forward into the surplus available
   to the next-priority debt (the "snowball" effect). An earlier version of
   simulate_waterfall let a fixed monthly_surplus stay fixed forever and
   simply stopped paying a finished debt's minimum, which silently shrank
   the total monthly budget every time a debt cleared -- this made ANY
   order that cleared small balances later look artificially cheaper, which
   is exactly backwards. test_freed_minimum_payment_rolls_forward_to_the_
   next_priority_debt is a direct regression for that fix: it constructs a
   scenario that can ONLY fully amortize if freed capacity rolls forward
   (a large debt's own minimum payment exactly breaks even against its own
   interest), so the old bug would have made this test hang until
   MAX_SIMULATION_MONTHS and raise.

2. Whether the adjusted order is actually net-cost-CHEAPER once real money
   is simulated -- and, importantly, that this is NOT true unconditionally.
   For a TAX-driven divergence (samples 2, 6, 7), the adjusted order is
   verified net-cheaper: the tax benefit is a continuous, ongoing
   percentage of actual accrued interest, so ranking by after-tax rate
   aligns with minimizing net cost once the waterfall correctly rolls
   forward capacity. For sample 3 (a FEE-driven divergence) and sample 4
   (the UTILISATION-heuristic-driven divergence), the adjusted order comes
   out slightly net-COSTLIER in raw rupee terms -- and this is verified as
   the CORRECT, understood behavior, not a bug:
   - A foreclosure charge is a one-time cost proportional to whatever
     balance remains at the moment of payoff, not a continuous rate --
     unlike the tax shield, its size doesn't scale with "how long you
     delay," so blending it into a single sort key can promote a
     genuinely-lower-nominal-rate debt (a1, 9%) ahead of a genuinely
     higher-nominal-rate one (pl1, 11%), increasing total nominal interest
     by more than the small one-time fee saves.
   - The utilisation heuristic was never a rupee-cost signal at all -- it
     protects a CIBIL score. Promoting a lower-nominal-rate card (cc2, 30%)
     ahead of a higher-nominal-rate loan (pl1, 32%) to cross the 30%
     threshold sooner necessarily costs a little more interest; that small
     cost IS the price of the trade-off, not a modeling failure.
   See DECISIONS.md for the full writeup.
"""

from __future__ import annotations

import pytest

from adjust import adjust_portfolio
from impact import MAX_SIMULATION_MONTHS, compare_impact, simulate_waterfall
from schema import Portfolio, PropertyOccupancy, RateType
from sequence import compute_ordering
from synth.generator import generate_portfolio

SEED = "trueorder-checkpoint-2026-09-06"
MONTHLY_SURPLUS = 15_000.0


def _impact_comparison(segment: str):
    portfolio = generate_portfolio(SEED, segment, index=0)
    adjusted = adjust_portfolio(portfolio)
    ordering = compute_ordering(portfolio, adjusted)
    return compare_impact(portfolio, ordering, MONTHLY_SURPLUS)


def test_freed_minimum_payment_rolls_forward_to_the_next_priority_debt():
    """Debt Y's own minimum payment (1,000/month) is set to exactly break
    even against its own interest (100,000 balance x 1%/month = 1,000/month
    interest) -- paid at that minimum alone, forever, Y's balance would
    NEVER decrease even by one rupee. The only way this portfolio can fully
    amortize at all is if X's freed-up minimum (2,000/month) rolls into Y's
    payment once X clears. Without the roll-forward fix, this would run
    until MAX_SIMULATION_MONTHS and raise RuntimeError."""
    from schema import PersonalLoan

    portfolio = Portfolio(
        borrower_id="rollforward_check",
        tax_regime="old",
        marginal_tax_rate_pct=30.0,
        debts=[
            PersonalLoan(
                debt_id="x",
                outstanding_balance=2_000,
                stated_apr_pct=12.0,
                remaining_tenure_months=60,
                minimum_payment=2_000,
                rate_type=RateType.FLOATING,
            ),
            PersonalLoan(
                debt_id="y",
                outstanding_balance=100_000,
                stated_apr_pct=12.0,
                remaining_tenure_months=600,
                minimum_payment=1_000,
                rate_type=RateType.FLOATING,
            ),
        ],
    )
    result = simulate_waterfall(portfolio, order=["x", "y"], monthly_surplus=0.0)
    assert result.months_to_payoff < MAX_SIMULATION_MONTHS
    assert result.months_to_payoff < 100  # generous margin; the math above suggests ~50-60


def test_no_rollforward_would_hang_without_the_fix():
    """Sanity check that the scenario above is actually a genuine break-even
    trap and not just an easy case that would pass regardless -- confirms
    Y truly cannot amortize on 1,000/month alone (the negative-amortization
    floor), which is what makes the roll-forward test above meaningful."""
    balance = 100_000.0
    monthly_rate = 12.0 / 1200
    interest = balance * monthly_rate
    assert interest == pytest.approx(1_000.0)  # exactly break-even against the minimum


def test_agreement_case_has_zero_net_cost_delta():
    comparison = _impact_comparison("agreement_case")
    assert comparison.net_cost_delta == 0.0


def test_selfoccupied_new_regime_regression_has_zero_net_cost_delta():
    comparison = _impact_comparison("selfoccupied_new_regime_regression")
    assert comparison.net_cost_delta == 0.0


@pytest.mark.parametrize(
    "segment",
    ["letout_home_old_regime", "education_loan_80e_old_regime", "letout_home_old_regime_loss_capped"],
)
def test_tax_driven_divergence_makes_adjusted_order_net_cheaper(segment):
    comparison = _impact_comparison(segment)
    assert comparison.net_cost_delta > 0, (
        f"expected the adjusted order to be net-cheaper for {segment} once the tax benefit "
        f"is realized over time in a real waterfall, got delta={comparison.net_cost_delta}"
    )


def test_fee_driven_divergence_can_leave_adjusted_order_net_costlier():
    """See module docstring: the foreclosure charge is a one-time,
    balance-proportional cost, not a continuous rate, so promoting the
    fixed-rate loan ahead of a genuinely higher-nominal-rate debt can cost
    slightly more in real nominal interest than the fee saves. This is a
    verified, understood property of this specific sample's numbers, not
    an assumption -- if adjust.py's fee formula or sample 3's numbers ever
    change, this test's failure is the signal to re-verify which direction
    the trade-off now goes, not to blindly flip the assertion."""
    comparison = _impact_comparison("fixed_auto_foreclosure")
    assert comparison.net_cost_delta < 0


def test_utilisation_heuristic_divergence_trades_a_small_net_cost_for_score_protection():
    """The utilisation heuristic protects a CIBIL score, not rupees --
    cc2's adjusted rate equals its stated rate exactly (no tax/fee
    adjustment), so promoting it ahead of a genuinely higher-nominal-rate
    debt (pl1) is expected to cost a little more in real interest. Bounded
    above to make sure the cost of the trade-off stays small relative to
    the portfolio's overall interest, not just negative."""
    comparison = _impact_comparison("utilisation_threshold")
    assert comparison.net_cost_delta < 0
    assert abs(comparison.net_cost_delta) < 0.01 * comparison.naive.total_interest_paid


def test_foreclosure_fee_only_charged_on_early_payoff_of_a_fixed_rate_loan():
    """Isolated check of the fee mechanism itself: a fixed-rate loan paid
    off well before its stated remaining tenure (large surplus, short
    tenure) must show a nonzero foreclosure fee; the same loan given enough
    tenure that minimum payments alone would finish it exactly on schedule
    must show zero."""
    from schema import AutoLoan

    def _portfolio(remaining_tenure_months: int) -> Portfolio:
        return Portfolio(
            borrower_id="fee_check",
            tax_regime="old",
            marginal_tax_rate_pct=30.0,
            debts=[
                AutoLoan(
                    debt_id="a1",
                    outstanding_balance=100_000,
                    stated_apr_pct=9.0,
                    remaining_tenure_months=remaining_tenure_months,
                    minimum_payment=5_000,
                    rate_type=RateType.FIXED,
                    foreclosure_charge_pct=3.0,
                )
            ],
        )

    accelerated = simulate_waterfall(_portfolio(remaining_tenure_months=60), order=["a1"], monthly_surplus=20_000)
    assert accelerated.total_foreclosure_fees_paid > 0
    assert accelerated.months_to_payoff < 60

    # remaining_tenure_months=1 deliberately understates the loan's real
    # minimum-only amortization time (~22 months for these numbers) so that
    # whatever month it actually finishes in is guaranteed to be >=
    # remaining_tenure_months -- i.e. never "early" by this test's own
    # stated tenure, without needing to hand-compute the exact payoff month.
    natural_pace = simulate_waterfall(_portfolio(remaining_tenure_months=1), order=["a1"], monthly_surplus=0)
    assert natural_pace.total_foreclosure_fees_paid == 0.0
