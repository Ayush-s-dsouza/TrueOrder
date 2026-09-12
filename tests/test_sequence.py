"""Each named segment's naive-vs-adjusted ordering is checked against the
hand-worked expectation computed by hand against tax_rules.py/fee_rules.py
before the generator numbers were finalized (see synth/generator.py's
module docstring) -- this is what turns "the demo script printed something
plausible-looking" into an actual regression test.

Every divergence is also checked against its mechanism attribution (see
schema.py's DivergenceMechanism/DivergenceRationale and sequence.py's
compute_divergence_rationale) -- this project's single most important
distinction (see DECISIONS.md) is that a divergence is never left as a bare
rank change with no stated reason, and the reason is never a generic
"cheaper," but one of several specific, differently-shaped claims: tax
(mechanically cheaper when the deductible fraction is constant over the
debt's life -- NOT a universal guarantee, see test_impact.py's capped-
fraction correction for when it isn't), fee (a ranking justification, not
a savings guarantee -- can go either way in a real waterfall, see
test_impact.py), utilisation (explicitly not a rupee claim at all), or
displaced (no claim about this debt at all -- it moved only because a
neighbour was promoted past it, and `displaced_by` names which one).
This test file only checks ATTRIBUTION correctness (is h1 correctly
tagged as a tax mechanism, with a positive rupee effect) -- whether that
mechanism's real waterfall outcome is unconditionally favorable is
test_impact.py's question, not this file's.

Regenerates portfolios directly from synth.generator (same SEED as
demo_checkpoint.py) rather than reading samples/*.json, so this test can't
silently pass against a stale committed sample file if generator.py changes
without the JSON being regenerated.
"""

from __future__ import annotations

import pytest

from adjust import adjust_portfolio
from schema import (
    DivergenceMechanism,
    HomeLoan,
    PersonalLoan,
    Portfolio,
    PropertyOccupancy,
    RateType,
    TaxRegime,
)
from sequence import compute_ordering
from synth.generator import generate_portfolio

SEED = "trueorder-checkpoint-2026-09-06"


def _ordering(segment: str):
    portfolio = generate_portfolio(SEED, segment, index=0)
    adjusted = adjust_portfolio(portfolio)
    return compute_ordering(portfolio, adjusted)


def test_agreement_case_naive_and_adjusted_orders_are_identical():
    ordering = _ordering("agreement_case")
    assert ordering.naive_order == ordering.adjusted_order == ["cc1", "cc2", "pl1"]
    assert ordering.divergence_points == []
    assert ordering.divergence_rationale == {}


def test_letout_home_old_regime_diverges_on_tax():
    ordering = _ordering("letout_home_old_regime")
    assert ordering.naive_order == ["cc1", "h1", "pl1"]
    assert ordering.adjusted_order == ["cc1", "pl1", "h1"]
    assert set(ordering.divergence_points) == {"h1", "pl1"}

    # h1 has its own real tax adjustment: a mechanically-guaranteed rupee
    # saving (once realized in a waterfall), never a "traded_for" trade-off.
    assert ordering.divergence_rationale["h1"].mechanism == DivergenceMechanism.TAX
    assert ordering.divergence_rationale["h1"].net_rupee_effect > 0
    assert ordering.divergence_rationale["h1"].traded_for is None

    # pl1 has no adjustment of its own -- it was passively displaced by h1's
    # tax-driven promotion. It is NOT tagged "tax": it has no tax deduction,
    # and borrowing h1's label would assert something false about it.
    assert ordering.divergence_rationale["pl1"].mechanism == DivergenceMechanism.DISPLACED
    assert ordering.divergence_rationale["pl1"].net_rupee_effect == 0.0
    assert ordering.divergence_rationale["pl1"].traded_for is None
    assert ordering.divergence_rationale["pl1"].displaced_by == "h1"


def test_fixed_auto_foreclosure_diverges_on_fees():
    ordering = _ordering("fixed_auto_foreclosure")
    assert ordering.naive_order == ["cc1", "pl1", "a1"]
    assert ordering.adjusted_order == ["cc1", "a1", "pl1"]
    assert set(ordering.divergence_points) == {"a1", "pl1"}

    # a1's own foreclosure charge is a real ranking justification -- but a
    # NEGATIVE net_rupee_effect, and never a promise about the real
    # waterfall outcome (that's test_impact.py's job, and it can go either
    # way for exactly this mechanism, see DECISIONS.md).
    assert ordering.divergence_rationale["a1"].mechanism == DivergenceMechanism.FEE
    assert ordering.divergence_rationale["a1"].net_rupee_effect < 0
    assert ordering.divergence_rationale["a1"].traded_for is None

    # pl1 is floating-rate: fee_rules says no foreclosure charge can apply
    # to it at all, so tagging it "fee" would have been a false label.
    assert ordering.divergence_rationale["pl1"].mechanism == DivergenceMechanism.DISPLACED
    assert ordering.divergence_rationale["pl1"].net_rupee_effect == 0.0
    assert ordering.divergence_rationale["pl1"].displaced_by == "a1"


def test_utilisation_threshold_diverges_on_heuristic():
    ordering = _ordering("utilisation_threshold")
    assert ordering.naive_order == ["cc1", "pl1", "cc2"]
    assert ordering.adjusted_order == ["cc1", "cc2", "pl1"]
    assert set(ordering.divergence_points) == {"cc2", "pl1"}

    # cc2 is the debt actually making the utilisation move: net_rupee_effect
    # exactly 0.0 (no tax/fee adjustment fires for a credit card), and
    # traded_for MUST be populated -- this is the one mechanism that is
    # explicitly not a cost-savings claim, enforced by schema.py's own
    # validator, not just by convention here.
    cc2_rationale = ordering.divergence_rationale["cc2"]
    assert cc2_rationale.mechanism == DivergenceMechanism.UTILISATION
    assert cc2_rationale.net_rupee_effect == 0.0
    assert cc2_rationale.traded_for is not None
    assert "credit score" in cc2_rationale.traded_for.lower()
    assert "rupee" in cc2_rationale.traded_for.lower()
    assert cc2_rationale.displaced_by is None

    # pl1 is a PERSONAL LOAN -- it has no utilisation dimension whatsoever
    # (utilisation is a credit-card concept). Labelling it "utilisation"
    # with a credit-score traded_for, as the borrowing scheme used to, told
    # the explanation layer something categorically untrue about it.
    pl1_rationale = ordering.divergence_rationale["pl1"]
    assert pl1_rationale.mechanism == DivergenceMechanism.DISPLACED
    assert pl1_rationale.net_rupee_effect == 0.0
    assert pl1_rationale.traded_for is None
    assert pl1_rationale.displaced_by == "cc2"


def test_selfoccupied_new_regime_regression_has_no_divergence():
    ordering = _ordering("selfoccupied_new_regime_regression")
    assert ordering.naive_order == ordering.adjusted_order == ["cc1", "pl1", "h1"]
    assert ordering.divergence_points == []
    assert ordering.divergence_rationale == {}


def test_education_loan_80e_old_regime_diverges_on_tax():
    ordering = _ordering("education_loan_80e_old_regime")
    assert ordering.naive_order == ["cc1", "e1", "pl1"]
    assert ordering.adjusted_order == ["cc1", "pl1", "e1"]
    assert set(ordering.divergence_points) == {"e1", "pl1"}

    assert ordering.divergence_rationale["e1"].mechanism == DivergenceMechanism.TAX
    assert ordering.divergence_rationale["e1"].net_rupee_effect > 0
    assert ordering.divergence_rationale["pl1"].mechanism == DivergenceMechanism.DISPLACED
    assert ordering.divergence_rationale["pl1"].net_rupee_effect == 0.0
    assert ordering.divergence_rationale["pl1"].displaced_by == "e1"


def test_compound_tax_and_fee_on_the_same_debt_raises_through_the_real_pipeline():
    """schema.py's DivergenceRationale validator proves the TYPE can't be
    constructed with more than one mechanism (see test_schema.py). This
    proves the separate, equally important fact: the PIPELINE never TRIES
    to build one when a real, ambiguous PORTFOLIO reaches it. A fixed-rate,
    let-out home loan under the old regime is the one debt shape in this
    schema that can genuinely trigger both mechanisms on the SAME debt --
    Section 24(b) fires (let-out, old regime) AND the RBI foreclosure
    exemption doesn't apply (fixed rate), so both tax_delta and fee_delta
    are nonzero for h1 at once. Fed through compute_ordering (which calls
    sequence.compute_divergence_rationale internally, the actual pipeline
    entry point a caller would use, not just the internal helper in
    isolation), this must raise rather than silently picking one mechanism
    -- exactly the category-error risk this whole distinction exists to
    eliminate. No synthetic segment constructs this shape (see
    DECISIONS.md and synth/segments.py -- every real Indian home loan is
    overwhelmingly floating-rate in practice, so this is a deliberately
    constructed edge case, not a gap in segment coverage)."""
    portfolio = Portfolio(
        borrower_id="compound_tax_and_fee_check",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            HomeLoan(
                debt_id="h1",
                outstanding_balance=1_000_000,
                stated_apr_pct=11.0,
                remaining_tenure_months=120,
                minimum_payment=15_000,
                rate_type=RateType.FIXED,
                foreclosure_charge_pct=3.0,
                occupancy=PropertyOccupancy.LET_OUT,
                annual_rental_income=100_000,
            ),
            PersonalLoan(
                debt_id="pl1",
                outstanding_balance=200_000,
                stated_apr_pct=10.0,
                remaining_tenure_months=24,
                minimum_payment=10_000,
                rate_type=RateType.FLOATING,
            ),
        ],
    )
    adjusted = adjust_portfolio(portfolio)

    # Confirm the setup actually triggers both mechanisms on h1 -- a
    # not-raising failure here would mean the test stopped testing what it
    # claims to, not that the pipeline is safe.
    [h1_adjusted] = [ad for ad in adjusted if ad.debt.debt_id == "h1"]
    assert h1_adjusted.after_tax_rate_pct < h1_adjusted.debt.stated_apr_pct  # tax fires
    assert h1_adjusted.foreclosure_adjusted_rate_pct > h1_adjusted.debt.stated_apr_pct  # fee fires

    with pytest.raises(ValueError, match="more than one active mechanism"):
        compute_ordering(portfolio, adjusted)
