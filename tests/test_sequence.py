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
"cheaper," but one of three specific, differently-shaped claims: tax
(mechanically cheaper), fee (a ranking justification, not a savings
guarantee -- can go either way in a real waterfall, see test_impact.py),
or utilisation (explicitly not a rupee claim at all).

Regenerates portfolios directly from synth.generator (same SEED as
demo_checkpoint.py) rather than reading samples/*.json, so this test can't
silently pass against a stale committed sample file if generator.py changes
without the JSON being regenerated.
"""

from __future__ import annotations

from adjust import adjust_portfolio
from schema import DivergenceMechanism
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
    # tax-driven promotion, so it borrows h1's mechanism with zero effect.
    assert ordering.divergence_rationale["pl1"].mechanism == DivergenceMechanism.TAX
    assert ordering.divergence_rationale["pl1"].net_rupee_effect == 0.0
    assert ordering.divergence_rationale["pl1"].traded_for is None


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

    assert ordering.divergence_rationale["pl1"].mechanism == DivergenceMechanism.FEE
    assert ordering.divergence_rationale["pl1"].net_rupee_effect == 0.0


def test_utilisation_threshold_diverges_on_heuristic():
    ordering = _ordering("utilisation_threshold")
    assert ordering.naive_order == ["cc1", "pl1", "cc2"]
    assert ordering.adjusted_order == ["cc1", "cc2", "pl1"]
    assert set(ordering.divergence_points) == {"cc2", "pl1"}

    # Both entries: mechanism=utilisation, net_rupee_effect exactly 0.0 (no
    # tax/fee adjustment fires for either debt), and traded_for MUST be
    # populated -- this is the one mechanism that is explicitly not a
    # cost-savings claim, enforced by schema.py's own validator, not just
    # by convention here.
    for debt_id in ("cc2", "pl1"):
        rationale = ordering.divergence_rationale[debt_id]
        assert rationale.mechanism == DivergenceMechanism.UTILISATION
        assert rationale.net_rupee_effect == 0.0
        assert rationale.traded_for is not None
        assert "credit score" in rationale.traded_for.lower()
        assert "rupee" in rationale.traded_for.lower()


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
    assert ordering.divergence_rationale["pl1"].mechanism == DivergenceMechanism.TAX
    assert ordering.divergence_rationale["pl1"].net_rupee_effect == 0.0
