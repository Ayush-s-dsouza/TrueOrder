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
   - TAX, CONSTANT-FRACTION CASE (samples 2, 6 -- letout_home_old_regime,
     education_loan_80e_old_regime): mechanically cheaper, ALWAYS, when it
     fires. net_cost_delta > 0 is a REQUIRED regression -- a failure here
     is a real bug. The tax benefit is a continuous, ongoing percentage of
     actual accrued interest, so ranking by after-tax rate provably
     aligns with minimizing net cost once the waterfall correctly rolls
     forward capacity.
   - TAX, CAPPED-FRACTION CASE (sample 7 --
     letout_home_old_regime_loss_capped): a CORRECTION to the guarantee
     above, found by running the eval at scale rather than trusting one
     hand-picked index (see DECISIONS.md). When a rupee cap actively binds
     (interest exceeds rental income plus the Rs 2L Section 71(3A) cap),
     the deductible fraction is NOT constant -- it improves as the balance
     amortizes down, since the fixed cap becomes a larger share of a
     shrinking interest amount. adjust.py's ranking uses a single
     point-in-time snapshot of that fraction, so for this segment it can
     no longer guarantee the sign of the real, simulated outcome: verified
     empirically across the eval manifest's 6 indices of this exact
     segment, 3 positive and 3 negative, all under 0.05% of net cost. Same
     STRUCTURAL class of finding as the fee mechanism below -- a static
     ranking heuristic doesn't guarantee a real waterfall outcome -- just
     discovered to also apply to a subset of tax cases this project
     originally, incorrectly, claimed were exempt.
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


@pytest.mark.parametrize("segment", ["letout_home_old_regime", "education_loan_80e_old_regime"])
def test_tax_mechanism_with_a_constant_shield_fraction_requires_net_cost_delta_positive(segment):
    """TAX guarantee, CORRECTLY SCOPED (see DECISIONS.md's correction --
    this test previously also covered letout_home_old_regime_loss_capped,
    which does NOT hold this guarantee, see the test below): when a debt's
    deductible_fraction is CONSTANT over its whole amortization -- true for
    both segments here, verified across all 6 eval-manifest indices of
    each, not just index 0 -- net_cost_delta > 0 is a REQUIRED regression.
    A constant fraction means the tax benefit is a continuous, ongoing
    percentage of actual accrued interest, the same "weighted balance over
    time" shape as the interest cost it discounts, so ranking by after-tax
    rate provably aligns with minimizing net cost. If this ever fails for
    either of these two segments, that is a real bug (in tax_rules.py,
    adjust.py, or the waterfall), not a "the trade-off went the other way
    this time" result -- unlike the capped case below, or the fee test."""
    comparison = _impact_comparison(segment)
    assert comparison.net_cost_delta > 0, (
        f"expected the adjusted order to be net-cheaper for {segment} once the tax benefit "
        f"is realized over time in a real waterfall, got delta={comparison.net_cost_delta}"
    )


def test_tax_mechanism_with_a_binding_cap_can_go_either_way():
    """CORRECTION to the guarantee above, found by running the eval at
    scale rather than trusting a single hand-picked index (see
    DECISIONS.md): letout_home_old_regime_loss_capped's home loan has a
    deductible_fraction that is NOT constant -- the Rs 2L Section 71(3A)
    cap is a FIXED rupee amount, so as the balance amortizes down and
    annual interest shrinks, that fixed cap becomes a LARGER fraction of a
    SMALLER number, meaning the shield genuinely IMPROVES over the loan's
    life instead of staying flat. adjust.py's ranking uses a single
    point-in-time snapshot of that fraction, so for this segment it can
    no longer guarantee the real, time-varying simulated outcome always
    favors the adjusted order -- confirmed empirically across the eval
    manifest's 6 indices of this exact segment: 3 positive, 3 negative,
    all tiny in magnitude relative to the multi-million-rupee net costs
    involved (under 0.05% of net cost in every case seen). This is
    structurally the SAME class of finding as the fee mechanism's "can go
    either way" property (a static ranking heuristic doesn't guarantee a
    real waterfall outcome) -- it just turns out to also apply to a
    SUBSET of tax cases this project originally, incorrectly, claimed were
    exempt. This test proves the nuance is real and stable (both signs
    genuinely occur across the segment's natural jitter range), not an
    isolated fluke."""
    deltas = [_capped_delta_for_index(index) for index in range(6)]
    assert any(d > 0 for d in deltas), "expected at least one index to favor the adjusted order"
    assert any(d < 0 for d in deltas), (
        "expected at least one index to favor the naive order -- if this now fails, the cap "
        "dynamic may have changed; re-verify before treating it as newly, unconditionally positive"
    )
    assert all(abs(d) < 0.001 * 4_000_000 for d in deltas), "expected the sign flip to stay a tiny fraction of net cost, not a large one"


def _capped_delta_for_index(index: int) -> float:
    # Uses the eval's own seed, not this file's SEED constant -- this is
    # the exact seed/index combination that surfaced the finding (see
    # DECISIONS.md), so reproducing it verbatim matters more than
    # consistency with this file's other fixtures.
    portfolio = generate_portfolio("trueorder-eval-2026-09-06", "letout_home_old_regime_loss_capped", index)
    adjusted = adjust_portfolio(portfolio)
    ordering = compute_ordering(portfolio, adjusted)
    return compare_impact(portfolio, ordering, MONTHLY_SURPLUS).net_cost_delta


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
