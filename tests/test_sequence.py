"""Each named segment's naive-vs-adjusted ordering is checked against the
hand-worked expectation computed by hand against tax_rules.py/fee_rules.py
before the generator numbers were finalized (see synth/generator.py's
module docstring) -- this is what turns "the demo script printed something
plausible-looking" into an actual regression test.

Regenerates portfolios directly from synth.generator (same SEED as
demo_checkpoint.py) rather than reading samples/*.json, so this test can't
silently pass against a stale committed sample file if generator.py changes
without the JSON being regenerated.
"""

from __future__ import annotations

from adjust import adjust_portfolio
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


def test_letout_home_old_regime_diverges_on_tax():
    ordering = _ordering("letout_home_old_regime")
    assert ordering.naive_order == ["cc1", "h1", "pl1"]
    assert ordering.adjusted_order == ["cc1", "pl1", "h1"]
    assert set(ordering.divergence_points) == {"h1", "pl1"}


def test_fixed_auto_foreclosure_diverges_on_fees():
    ordering = _ordering("fixed_auto_foreclosure")
    assert ordering.naive_order == ["cc1", "pl1", "a1"]
    assert ordering.adjusted_order == ["cc1", "a1", "pl1"]
    assert set(ordering.divergence_points) == {"a1", "pl1"}


def test_utilisation_threshold_diverges_on_heuristic():
    ordering = _ordering("utilisation_threshold")
    assert ordering.naive_order == ["cc1", "pl1", "cc2"]
    assert ordering.adjusted_order == ["cc1", "cc2", "pl1"]
    assert set(ordering.divergence_points) == {"cc2", "pl1"}


def test_selfoccupied_new_regime_regression_has_no_divergence():
    ordering = _ordering("selfoccupied_new_regime_regression")
    assert ordering.naive_order == ordering.adjusted_order == ["cc1", "pl1", "h1"]
    assert ordering.divergence_points == []


def test_education_loan_80e_old_regime_diverges_on_tax():
    ordering = _ordering("education_loan_80e_old_regime")
    assert ordering.naive_order == ["cc1", "e1", "pl1"]
    assert ordering.adjusted_order == ["cc1", "pl1", "e1"]
    assert set(ordering.divergence_points) == {"e1", "pl1"}
