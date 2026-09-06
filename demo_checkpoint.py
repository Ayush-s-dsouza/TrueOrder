"""Checkpoint-only script: generates the 6 named sample portfolios into
samples/, runs PROFILE -> ADJUST -> SEQUENCE on each, and prints both
orderings side by side with every adjustment note that produced a
divergence. Not the final CLI -- run.py (step 7, not built this phase) will
supersede this once impact.py/emit.py/audit.py exist.
"""

from __future__ import annotations

from pathlib import Path

from adjust import adjust_portfolio
from impact import compare_impact
from schema import Portfolio
from sequence import compute_ordering
from synth.generator import generate_portfolio
from synth.segments import SEGMENT_DESCRIPTIONS

SEED = "trueorder-checkpoint-2026-09-06"
MONTHLY_SURPLUS = 15_000.0
SAMPLES_DIR = Path(__file__).parent / "samples"

SAMPLE_FILES = {
    "agreement_case": "sample_001_agreement_case.json",
    "letout_home_old_regime": "sample_002_letout_home_old_regime.json",
    "fixed_auto_foreclosure": "sample_003_fixed_auto_foreclosure.json",
    "utilisation_threshold": "sample_004_utilisation_threshold.json",
    "selfoccupied_new_regime_regression": "sample_005_selfoccupied_new_regime_regression.json",
    "education_loan_80e_old_regime": "sample_006_education_loan_80e_old_regime.json",
    "letout_home_old_regime_loss_capped": "sample_007_letout_home_old_regime_loss_capped.json",
}


def generate_samples() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    for segment, filename in SAMPLE_FILES.items():
        portfolio = generate_portfolio(SEED, segment, index=0)
        (SAMPLES_DIR / filename).write_text(portfolio.model_dump_json(indent=2), encoding="utf-8")


def show_sample(segment: str, filename: str) -> None:
    portfolio = Portfolio.model_validate_json((SAMPLES_DIR / filename).read_text(encoding="utf-8"))
    adjusted = adjust_portfolio(portfolio)
    ordering = compute_ordering(portfolio, adjusted)
    adjusted_by_id = {ad.debt.debt_id: ad for ad in adjusted}

    print("=" * 88)
    print(f"{filename}  --  segment: {segment}")
    print(SEGMENT_DESCRIPTIONS[segment])
    print("-" * 88)
    print(f"{'debt_id':10}{'type':16}{'stated%':>10}{'after_tax%':>12}{'fee_adj%':>10}{'util_score':>12}")
    for debt in portfolio.debts:
        ad = adjusted_by_id[debt.debt_id]
        print(
            f"{debt.debt_id:10}{debt.debt_type.value:16}{debt.stated_apr_pct:>10.2f}"
            f"{ad.after_tax_rate_pct:>12.2f}{ad.foreclosure_adjusted_rate_pct:>10.2f}"
            f"{ad.utilisation_priority_score:>12.1f}"
        )
    print()
    print(f"  naive order    (stated APR desc):     {ordering.naive_order}")
    print(f"  adjusted order (effective cost desc): {ordering.adjusted_order}")
    print(f"  divergence points:                    {ordering.divergence_points}")

    impact = compare_impact(portfolio, ordering, MONTHLY_SURPLUS)
    print(f"  -- impact, {MONTHLY_SURPLUS:.0f}/month surplus, real waterfall --")
    print(
        f"  naive   : interest={impact.naive.total_interest_paid:>12,.2f}  "
        f"fees={impact.naive.total_foreclosure_fees_paid:>8,.2f}  "
        f"tax_benefit={impact.naive.total_tax_benefit_realized:>10,.2f}  "
        f"net_cost={impact.naive.net_cost:>12,.2f}  months={impact.naive.months_to_payoff}"
    )
    print(
        f"  adjusted: interest={impact.adjusted.total_interest_paid:>12,.2f}  "
        f"fees={impact.adjusted.total_foreclosure_fees_paid:>8,.2f}  "
        f"tax_benefit={impact.adjusted.total_tax_benefit_realized:>10,.2f}  "
        f"net_cost={impact.adjusted.net_cost:>12,.2f}  months={impact.adjusted.months_to_payoff}"
    )
    print(f"  net_cost_delta (positive = adjusted cheaper): {impact.net_cost_delta:,.2f}")
    if ordering.divergence_points:
        print("  -- adjustment notes for diverging debts --")
        for debt_id in ordering.divergence_points:
            ad = adjusted_by_id[debt_id]
            print(f"  [{debt_id}] tax:  {ad.tax_adjustment_note}")
            print(f"  [{debt_id}] fee:  {ad.fee_adjustment_note}")
    print()


def main() -> None:
    generate_samples()
    for segment, filename in SAMPLE_FILES.items():
        show_sample(segment, filename)


if __name__ == "__main__":
    main()
