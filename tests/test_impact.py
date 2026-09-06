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

2. The project's central finding (see DECISIONS.md): "adjusted = cheaper"
   is not one blanket claim, and net_cost_delta does not mean the same
   thing for every divergence. It resolves into three mechanism-specific
   guarantees, each enforced by its own discipline below, not by a single
   "adjusted should win" assumption:
   - TAX (samples 2, 6, 7): mechanically cheaper, ALWAYS, when it fires.
     net_cost_delta > 0 is a REQUIRED regression -- a failure here is a
     real bug. The tax benefit is a continuous, ongoing percentage of
     actual accrued interest, so ranking by after-tax rate provably
     aligns with minimizing net cost once the waterfall correctly rolls
     forward capacity.
   - FEE (sample 3): a ranking justification, not a savings guarantee --
     can come out either cheaper or slightly costlier once realized. This
     sample's specific sign (costlier) is PINNED as a verified fact about
     these numbers, not asserted as a general property of the mechanism: a
     foreclosure charge is a one-time cost proportional to whatever
     balance remains at payoff, not a continuous rate, so promoting a
     genuinely-lower-nominal-rate debt (a1, 9%) ahead of a genuinely
     higher-nominal-rate one (pl1, 11%) increases total nominal interest
     by more than the one-time fee saves.
   - UTILISATION (sample 4): explicitly NOT a cost-savings claim.
     net_cost_delta is not the metric that judges this mechanism's
     correctness at all (DivergenceRationale.traded_for is, see
     test_sequence.py) -- this heuristic protects a CIBIL score, not
     rupees, so a small real cost from the trade is expected, not a
     modeling failure.
   Stating a utilisation promotion as a "cost saving," or a fee promotion
   as an unconditional one, would be a category error about what kind of
   claim is being made -- worse than a wrong number, since it looks
   plausible while answering a different question than the one asked. See
   DECISIONS.md for the full writeup.
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
def test_tax_mechanism_requires_net_cost_delta_positive(segment):
    """TAX guarantee: mechanically cheaper, ALWAYS, when it fires --
    net_cost_delta > 0 is a REQUIRED regression for every tax-driven
    sample, not a directional hope. If this ever fails, that is a real bug
    (in tax_rules.py, adjust.py, or the waterfall), not a "the trade-off
    went the other way this time" result -- unlike the fee test below."""
    comparison = _impact_comparison(segment)
    assert comparison.net_cost_delta > 0, (
        f"expected the adjusted order to be net-cheaper for {segment} once the tax benefit "
        f"is realized over time in a real waterfall, got delta={comparison.net_cost_delta}"
    )


def test_fee_mechanism_net_cost_delta_sign_is_pinned_not_asserted_as_general():
    """FEE guarantee: correctly identifies a debt as more expensive than
    naive assumes; can come out either cheaper OR slightly costlier once
    realized in a real waterfall (see DECISIONS.md) -- the sign is NOT
    something this mechanism promises in general. What IS pinned here is
    the verified, understood fact about THESE specific numbers: a
    foreclosure charge is a one-time, balance-proportional cost, not a
    continuous rate, so promoting a1 (9% nominal) ahead of pl1 (11%
    nominal, genuinely the more expensive debt) costs more in nominal
    interest (~Rs 2,314) than the fee difference saves (~Rs 27). If
    adjust.py's fee formula or sample 3's numbers ever change, this test's
    failure is the signal to re-verify which direction the trade-off now
    goes, never to blindly flip the assertion to keep the test green."""
    comparison = _impact_comparison("fixed_auto_foreclosure")
    assert comparison.net_cost_delta < 0


def test_utilisation_mechanism_net_cost_delta_is_not_the_correctness_metric():
    """UTILISATION guarantee: explicitly NOT a cost-savings claim -- there
    is no "correct sign" for net_cost_delta here at all, because this
    mechanism was never optimizing for rupees. What this test actually
    checks is that the real cost of the credit-score trade stays small
    relative to the portfolio (cc2's adjusted rate equals its stated rate
    exactly -- no tax/fee adjustment -- so any net_cost_delta here is pure
    trade-off cost, not a modeling artifact), and the SIGN itself is
    incidental, not the thing being verified. DivergenceRationale.traded_for
    is the field that actually judges this mechanism's correctness (see
    test_sequence.py), not this number."""
    comparison = _impact_comparison("utilisation_threshold")
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
