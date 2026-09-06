"""Unit tests for eval/metrics.py's text heuristics, using literal text
fixtures -- no API calls needed, since these are pure functions over
ground truth + a hand-written or previously-collected explanation string.

Three of these are direct regressions for real bugs found while building
this eval, not hypothetical edge cases: each was caught by comparing a
metric's verdict against a REAL collected explanation whose quality had
already been manually verified as correct, and finding the metric
disagreed (see DECISIONS.md for the full story of each).
"""

from __future__ import annotations

from adjust import adjust_portfolio
from eval.ground_truth import ground_truth_for_case
from eval.metrics import (
    COSTLIER_ADMISSION_PATTERN,
    _is_negated,
    _numbers_match,
    adjusted_order_sequence_correct,
    no_false_tax_claim_for_blocked_debts,
    no_invented_numbers,
)
from schema import HomeLoan, Portfolio, PropertyOccupancy, RateType, TaxRegime
from sequence import compute_ordering


def _case_for_portfolio(portfolio: Portfolio, monthly_surplus: float = 15_000.0) -> dict:
    return {"portfolio": portfolio.model_dump(mode="json"), "monthly_surplus": monthly_surplus}


def _self_occupied_new_regime_case() -> dict:
    portfolio = Portfolio(
        borrower_id="test",
        tax_regime=TaxRegime.NEW,
        marginal_tax_rate_pct=30.0,
        debts=[
            HomeLoan(
                debt_id="h1",
                outstanding_balance=3_500_000,
                stated_apr_pct=8.5,
                remaining_tenure_months=200,
                minimum_payment=32_000,
                rate_type=RateType.FLOATING,
                occupancy=PropertyOccupancy.SELF_OCCUPIED,
            )
        ],
    )
    return _case_for_portfolio(portfolio)


def test_costlier_admission_pattern_allows_a_rupee_figure_between_cost_and_more():
    """Real bug, found twice over via actual eval collection (see
    DECISIONS.md): a word-gap version of this pattern still missed real,
    honest admissions like "costs about Rs 1,417.93 more" and "costs you
    Rs 297.11 more", because a rupee figure's "." and "," aren't \\w
    characters, so a word-count-based gap silently undercounts them.
    Fixed to a character-based gap. All examples below are verbatim
    substrings from real collected baseline explanations that were
    manually confirmed correct and honest before being flagged as metric
    false negatives."""
    for text in (
        "it costs slightly more in practice",
        "the adjusted sequence costs about Rs 1,417.93 more over the life of the loans",
        "the adjusted path costs about Rs 587.64 more",
        "the adjusted plan costs Rs 1,891.08 more than the naive plan",
        "the adjusted path costs you Rs 297.11 more",
        "The adjusted order costs Rs 949.66 more",
    ):
        assert COSTLIER_ADMISSION_PATTERN.search(text), f"expected a match in: {text!r}"


def test_no_invented_numbers_allows_the_interest_and_fee_deltas():
    """Real bug: a genuinely correct explanation said "the adjusted path
    incurs Rs 1,951.23 more in interest even though it trims foreclosure
    fees by Rs 60.15" -- both numbers are exact, correct differences
    between the given naive/adjusted total_interest_paid and
    total_foreclosure_fees_paid figures, not fabrications. Verified against
    the real case that surfaced this (fixed_auto_foreclosure_005)."""
    from schema import AutoLoan, PersonalLoan

    portfolio = Portfolio(
        borrower_id="test",
        tax_regime=TaxRegime.NEW,
        marginal_tax_rate_pct=30.0,
        debts=[
            PersonalLoan(
                debt_id="pl1", outstanding_balance=300_000, stated_apr_pct=11.0,
                remaining_tenure_months=30, minimum_payment=12_000, rate_type=RateType.FLOATING,
            ),
            AutoLoan(
                debt_id="a1", outstanding_balance=400_000, stated_apr_pct=9.0,
                remaining_tenure_months=18, minimum_payment=24_000,
                rate_type=RateType.FIXED, foreclosure_charge_pct=4.0,
            ),
        ],
    )
    gt = ground_truth_for_case(_case_for_portfolio(portfolio))
    interest_delta = abs(gt.impact.adjusted.total_interest_paid - gt.impact.naive.total_interest_paid)
    fee_delta = abs(gt.impact.adjusted.total_foreclosure_fees_paid - gt.impact.naive.total_foreclosure_fees_paid)
    text = (
        f"The adjusted path incurs Rs {interest_delta:,.2f} more in interest even though it "
        f"trims foreclosure fees by Rs {fee_delta:,.2f}."
    )
    ok, count = no_invented_numbers(text, gt)
    assert ok, f"expected the derived deltas to be allowed, got {count} invented numbers"


def test_numbers_match_ignores_sign():
    """Real bug: a net_cost_delta of -949.66 was correctly restated in
    prose as "the adjusted order costs Rs 949.66 more" -- a faithful
    restatement of the magnitude with flipped sign framing, which the
    original signed comparison flagged as a fabricated number."""
    assert _numbers_match(949.66, [-949.6645457875056])
    assert not _numbers_match(949.66, [100.0, 200.0])


def test_is_negated_catches_denial_phrasing():
    """Real bug: "there are no tax deductions" matched the false-tax-claim
    pattern on its "tax deduction" substring and was flagged as a
    fabricated benefit -- exactly backwards, since the sentence correctly
    DENIES a deduction applies."""
    text = "because there are no tax deductions, foreclosure charges, or utilisation-crossing situations"
    match_start = text.index("tax deductions")
    assert _is_negated(text, match_start)

    text2 = "you get a genuine tax deduction this year"
    match_start2 = text2.index("tax deduction")
    assert not _is_negated(text2, match_start2)


def test_no_false_tax_claim_for_blocked_debts_ignores_correct_denials():
    case = _self_occupied_new_regime_case()
    gt = ground_truth_for_case(case)
    text = (
        "Your home loan (h1) does not qualify for a Section 24(b) deduction because it is "
        "self-occupied under the new tax regime, so there are no tax deductions here."
    )
    assert no_false_tax_claim_for_blocked_debts(text, gt) is True


def test_no_false_tax_claim_for_blocked_debts_still_catches_a_real_false_claim():
    """Sanity check that the negation fix didn't neuter the check entirely
    -- an actual false claim (no denial language nearby) must still fail."""
    case = _self_occupied_new_regime_case()
    gt = ground_truth_for_case(case)
    text = "Your home loan (h1) gets a nice tax deduction this year under Section 24(b)."
    assert no_false_tax_claim_for_blocked_debts(text, gt) is False


def test_no_false_tax_claim_returns_none_when_not_applicable():
    portfolio = Portfolio(
        borrower_id="test",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            HomeLoan(
                debt_id="h1",
                outstanding_balance=3_500_000,
                stated_apr_pct=8.5,
                remaining_tenure_months=200,
                minimum_payment=32_000,
                rate_type=RateType.FLOATING,
                occupancy=PropertyOccupancy.LET_OUT,
                annual_rental_income=400_000,
            )
        ],
    )
    gt = ground_truth_for_case(_case_for_portfolio(portfolio))
    assert no_false_tax_claim_for_blocked_debts("anything at all", gt) is None


def test_order_sequence_correct_finds_explicit_listing():
    """Real bug: the original heuristic used each debt's FIRST occurrence
    anywhere in the text, but naive order is conventionally described
    first in prose -- so on any case where naive and adjusted share a debt
    at different positions, the check silently verified the NAIVE
    sequence instead. This fixture reproduces that exact shape: naive
    (cc1, pl1, a1) stated before adjusted (cc1, a1, pl1)."""
    from schema import AutoLoan, PersonalLoan

    portfolio = Portfolio(
        borrower_id="test",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            PersonalLoan(
                debt_id="pl1", outstanding_balance=300_000, stated_apr_pct=11.0,
                remaining_tenure_months=30, minimum_payment=12_000, rate_type=RateType.FLOATING,
            ),
            AutoLoan(
                debt_id="a1", outstanding_balance=400_000, stated_apr_pct=9.0,
                remaining_tenure_months=18, minimum_payment=24_000,
                rate_type=RateType.FIXED, foreclosure_charge_pct=4.0,
            ),
        ],
    )
    adjusted = adjust_portfolio(portfolio)
    ordering = compute_ordering(portfolio, adjusted)
    assert ordering.adjusted_order == ["a1", "pl1"]

    gt = ground_truth_for_case(_case_for_portfolio(portfolio))
    text = "The naive order is pl1, then a1. The adjusted order is a1, then pl1."
    assert adjusted_order_sequence_correct(text, gt) is True


def test_order_sequence_correct_accepts_shorthand_after_swap_narrative():
    """Real bug: a genuinely correct explanation described the change as a
    narrative ("swaps pl1 down to third and promotes cc2 to second")
    rather than only a flat listing, and a naive positional check across
    the WHOLE text failed because the narrative mentions the debts out of
    adjusted order. The actual explicit sequence ("cc1, then cc2, then
    pl1") appeared elsewhere in the same text as a tight, contiguous run --
    this is what the fix must find regardless of which label phrase (or no
    phrase at all) introduces it."""
    from schema import CreditCard

    portfolio = Portfolio(
        borrower_id="test",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            CreditCard(
                debt_id="cc1", outstanding_balance=90_000, stated_apr_pct=36.0,
                remaining_tenure_months=360, minimum_payment=4_500,
                current_utilisation_pct=60.0, aggregate_utilisation_pct=34.29,
            ),
            CreditCard(
                debt_id="cc2", outstanding_balance=30_000, stated_apr_pct=30.0,
                remaining_tenure_months=360, minimum_payment=1_500,
                current_utilisation_pct=15.0, aggregate_utilisation_pct=34.29,
            ),
        ],
    )
    from schema import PersonalLoan

    portfolio = portfolio.model_copy(
        update={
            "debts": portfolio.debts
            + [
                PersonalLoan(
                    debt_id="pl1", outstanding_balance=200_000, stated_apr_pct=32.0,
                    remaining_tenure_months=24, minimum_payment=10_000, rate_type=RateType.FLOATING,
                )
            ]
        }
    )
    gt = ground_truth_for_case(_case_for_portfolio(portfolio))
    assert gt.ordering.adjusted_order == ["cc1", "cc2", "pl1"]

    text = (
        "You should pay cc1 first, then cc2, then pl1 -- in shorthand, cc1, then cc2, then pl1. "
        "A bare APR-only tool would instead tell you cc1, then pl1, then cc2. "
        "The adjusted plan swaps pl1 down to third and promotes cc2 to second."
    )
    assert adjusted_order_sequence_correct(text, gt) is True


def test_order_sequence_correct_returns_none_when_a_debt_is_never_mentioned():
    from schema import PersonalLoan

    portfolio = Portfolio(
        borrower_id="test",
        tax_regime=TaxRegime.OLD,
        marginal_tax_rate_pct=30.0,
        debts=[
            PersonalLoan(
                debt_id="pl1", outstanding_balance=200_000, stated_apr_pct=10.0,
                remaining_tenure_months=24, minimum_payment=10_000, rate_type=RateType.FLOATING,
            ),
            PersonalLoan(
                debt_id="pl2", outstanding_balance=100_000, stated_apr_pct=9.0,
                remaining_tenure_months=24, minimum_payment=8_000, rate_type=RateType.FLOATING,
            ),
        ],
    )
    gt = ground_truth_for_case(_case_for_portfolio(portfolio))
    assert adjusted_order_sequence_correct("pl1 is your only debt mentioned here.", gt) is None
