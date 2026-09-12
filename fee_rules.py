"""Verified RBI rules on foreclosure/prepayment charges, plus documented
context (not computed logic) on credit-card minimum-amount-due and the
utilisation/CIBIL heuristic. Every rule below was verified via web search on
2026-09-06, current as of that date and subject to change via a future RBI
circular.

Zero LLM calls, zero imports beyond stdlib -- part of the deterministic core
(see tests/test_no_llm_imports.py).
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Foreclosure / prepayment charges -- floating vs fixed rate, individuals,
# non-business purposes.
#
# Banned since 2012/2014 RBI circulars for floating-rate HOME loans.
# Extended to ALL floating-rate term loans to individuals for non-business
# purposes (personal loans, auto loans, education loans, with or without
# co-obligants) by RBI/2019-20/29 DBR.Dir.BC.No.08/13.03.00/2019-20
# (2 Aug 2019).
# Consolidated and further extended (to business-purpose loans for
# individuals/MSEs too) by the Reserve Bank of India (Pre-payment Charges on
# Loans) Directions, 2025 (issued 2 Jul 2025), effective for loans
# sanctioned or renewed on or after 1 Jan 2026.
#
# Net rule: a FLOATING-rate loan to an individual for a non-business purpose
# carries NO foreclosure/prepayment charge -- settled RBI policy since 2019,
# now consolidated under the 2025 Directions.
#
# FIXED-rate loans are NOT covered by this prohibition -- lenders may charge
# a foreclosure fee per their own terms. Since the actual percentage varies
# by lender/product, it is always taken as an explicit input
# (`foreclosure_charge_pct`), never a hardcoded assumed number.
#
# Sources (verified 2026-09-06):
#   https://www.corporateprofessionals.com/articles/rbi-pre-payment-charges-on-loans-directions-2025-a-regulatory-overview-for-lenders-and-nbfcs/
#   https://vinodkothari.com/2019/08/faqs-nbfcs-not-to-charge-foreclosure-pre-payment-penalties-on-floating-rate-term-loans-for-individual-borrowers/
#   https://www.rbi.org.in/scripts/NotificationUser.aspx?Id=12878&Mode=0
#   https://www.iifl.com/blogs/other/car-loan-prepayment-rules-india
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeeAdjustmentResult:
    foreclosure_adjusted_rate_pct: float
    note: str


# How many months a debt would take to retire on its MINIMUM PAYMENT ALONE.
# This is the shared definition of "when would this loan have ended anyway",
# and both stages that care about foreclosure now key off it:
#   - fee_rules/adjust annualizes the one-time charge over this horizon
#   - impact charges the fee iff actual payoff lands BEFORE this month
#
# It exists because `remaining_tenure_months` is a free-floating stated
# field with no schema constraint tying it to balance/minimum_payment/APR,
# so it can contradict the loan's actual cash flows. Keying the two stages
# off that field independently made them disagree systematically: the
# shorter the stated tenure, the MORE adjust.py inflated the rate, while
# impact.py became LESS likely to ever charge the fee (a 1-month stated
# tenure produced a +60pp rate penalty for a fee the simulation then
# charged at Rs 0). Deriving the horizon from the same cash flows both
# stages already simulate removes that contradiction at its source.
#
# Foreclosure means "retired sooner than it otherwise would have been",
# which is this quantity -- not "sooner than a stated schedule field says".
MAX_PAYOFF_HORIZON_MONTHS = 600


def natural_payoff_months(
    *, outstanding_balance: float, stated_apr_pct: float, minimum_payment: float
) -> int | None:
    """Months to retire this debt on its minimum payment alone, or None if
    it never amortizes (minimum payment never exceeds accruing interest).
    Deliberately mirrors impact.py's own per-month arithmetic (accrue, then
    pay) so the two stages cannot drift apart on rounding."""
    balance = outstanding_balance
    monthly_rate = stated_apr_pct / 1200
    for month in range(1, MAX_PAYOFF_HORIZON_MONTHS + 1):
        balance += balance * monthly_rate
        balance -= min(minimum_payment, balance)
        if balance <= 1e-6:
            return month
    return None


def loan_foreclosure_adjustment(
    *,
    rate_type: str,
    stated_rate_pct: float,
    foreclosure_charge_pct: float | None,
    outstanding_balance: float,
    minimum_payment: float,
) -> FeeAdjustmentResult:
    """Applies to personal, home, and auto loans (term loans with a
    foreclosure concept). Not applicable to credit cards -- see
    credit_card_foreclosure_note() below. Education loans are also covered
    by the RBI floating-rate exemption in principle, but this project does
    not model a fee dimension for education loans (its defining dimension
    here is the Section 80E tax treatment) -- see DECISIONS.md.
    """
    if rate_type == "floating":
        return FeeAdjustmentResult(
            foreclosure_adjusted_rate_pct=stated_rate_pct,
            note=(
                "Floating-rate loan to an individual for a non-business purpose: "
                "no foreclosure/prepayment charge applies, per RBI/2019-20/29 "
                "(2 Aug 2019), consolidated under the RBI (Pre-payment Charges on "
                "Loans) Directions, 2025. Rate unchanged."
            ),
        )

    # rate_type == "fixed"
    assert foreclosure_charge_pct is not None, (
        "fixed-rate loan must carry foreclosure_charge_pct -- schema.py should "
        "have rejected this input before it reached fee_rules.py"
    )
    natural_months = natural_payoff_months(
        outstanding_balance=outstanding_balance,
        stated_apr_pct=stated_rate_pct,
        minimum_payment=minimum_payment,
    )

    if natural_months is not None and natural_months <= 1:
        # The loan retires next month on its minimum payment alone: there is
        # no acceleration window, so there is nothing to foreclose. impact.py
        # agrees (payoff can never land strictly before month 1), so both
        # stages report no charge rather than contradicting each other.
        return FeeAdjustmentResult(
            foreclosure_adjusted_rate_pct=stated_rate_pct,
            note=(
                f"Fixed-rate loan carrying a stated {foreclosure_charge_pct:.2f}% "
                f"foreclosure charge, but its minimum payment alone retires it "
                f"within a month -- there is no early-payoff window left to "
                f"foreclose, so no charge can be incurred. Rate unchanged."
            ),
        )

    horizon_months = natural_months if natural_months is not None else MAX_PAYOFF_HORIZON_MONTHS
    horizon_years = horizon_months / 12
    annualized_charge_pct = foreclosure_charge_pct / horizon_years
    adjusted_rate = stated_rate_pct + annualized_charge_pct
    never_note = (
        ""
        if natural_months is not None
        else " (its minimum payment never amortizes the balance, so the horizon is "
        f"capped at {MAX_PAYOFF_HORIZON_MONTHS} months)"
    )
    return FeeAdjustmentResult(
        foreclosure_adjusted_rate_pct=adjusted_rate,
        note=(
            f"Fixed-rate loan: RBI's floating-rate prohibition does not apply, so "
            f"the lender's stated {foreclosure_charge_pct:.2f}% foreclosure charge "
            f"applies if it is paid off early. Annualized over the "
            f"{horizon_years:.1f} years this loan would otherwise take to retire "
            f"on its minimum payment alone{never_note}, this adds "
            f"{annualized_charge_pct:.2f} percentage points to the effective rate "
            f"({stated_rate_pct:.2f}% -> {adjusted_rate:.2f}%)."
        ),
    )


def credit_card_foreclosure_note(*, stated_rate_pct: float) -> FeeAdjustmentResult:
    """Credit cards are a revolving facility, not a term loan -- 'foreclosure'
    is not a meaningful concept for them. The rate is returned unchanged
    (never NaN or another sentinel -- a sentinel would silently corrupt any
    downstream sort/comparison); the note is what carries the "not
    applicable" meaning, so a reader can't mistake it for "zero charge,
    checked and confirmed absent"."""
    return FeeAdjustmentResult(
        foreclosure_adjusted_rate_pct=stated_rate_pct,
        note=(
            "Not applicable: a credit card is a revolving facility, not a term "
            "loan, so there is no foreclosure/prepayment charge to adjust for."
        ),
    )


# ---------------------------------------------------------------------------
# Credit card minimum-amount-due -- CONTEXT ONLY, not a rate adjustment.
#
# RBI Master Direction - Credit Card and Debit Card - Issuance and Conduct
# Directions, 2022 (21 Apr 2022, effective 1 Jul 2022, amended 7 Mar 2024)
# requires the MAD formula to avoid negative amortization: it must cover
# 100% of interest/fees/taxes for the cycle plus a defined share of
# principal. TrueOrder does not re-derive this formula -- each card's
# minimum_payment is a required input field, exactly as it always appears on
# a real statement. This citation exists so a reader understands *why* that
# input field can be trusted without TrueOrder recomputing it.
#
# Source (verified 2026-09-06):
#   https://ksandk.com/newsletter/rbi-master-direction-on-credit-debit-cards-updates/
# ---------------------------------------------------------------------------

MINIMUM_DUE_RBI_CITATION = (
    "RBI Master Direction - Credit Card and Debit Card - Issuance and Conduct "
    "Directions, 2022 (21 Apr 2022, effective 1 Jul 2022, amended 7 Mar 2024) "
    "requires minimum-amount-due formulas to avoid negative amortization. "
    "TrueOrder takes minimum_payment as a direct input rather than "
    "recomputing it, since issuers' exact formulas vary and the statement "
    "figure is already RBI-compliant by construction."
)


# ---------------------------------------------------------------------------
# Utilisation / CIBIL heuristic.
#
# The 30% aggregate-utilisation threshold is a real, widely-cited scoring
# factor. The commonly-quoted "30-80 point" swing is NOT a published,
# precise bureau figure -- no bureau publishes an exact point-impact table.
# This is stated explicitly as an uncertain heuristic range, same honesty
# standard as Prequal's enquiry_cost_model.json -- never presented as a
# precise, guaranteed number.
#
# Source (verified 2026-09-06):
#   https://www.iifl.com/blogs/credit-score/credit-utilisation-ratio-what-it-is-and-why-it-matters
# ---------------------------------------------------------------------------

UTILISATION_THRESHOLD_PCT = 30.0

UTILISATION_HEURISTIC_DISCLAIMER = (
    "The 30% aggregate-utilisation threshold is a real, widely-cited credit "
    "scoring factor. The score impact of crossing it is commonly cited in "
    "consumer-finance sources as roughly 30-80 CIBIL points, but this is a "
    "heuristic range, not a published precise figure from any bureau -- "
    "treat utilisation_priority_score as a directional signal, not a "
    "calibrated number."
)
