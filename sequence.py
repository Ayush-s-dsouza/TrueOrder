"""SEQUENCE stage: naive (stated-APR-only) vs adjusted (true-effective-cost)
repayment order, plus the divergence between them. Zero LLM calls -- part
of the deterministic core (see tests/test_no_llm_imports.py).

The utilisation-crossing override is applied as an explicit, separate step
after cost-based sorting, not folded into effective_cost_rank_input as a
rate-equivalent number -- the heuristic isn't calibrated in interest-rate
units (see fee_rules.UTILISATION_HEURISTIC_DISCLAIMER), so representing it
as one would overstate its precision. Instead: any credit card whose
paydown would cross the 30%-aggregate-utilisation threshold is promoted
ahead of every non-crossing debt, ranked among any other crossing cards by
their own effective cost. This is a deliberate, stated design choice, not a
hidden tiebreak.
"""

from __future__ import annotations

from schema import (
    AdjustedDebt,
    DivergenceMechanism,
    DivergenceRationale,
    Portfolio,
    RepaymentOrdering,
)

_EPSILON = 1e-9

_UTILISATION_TRADED_FOR = (
    "credit score protection (crossing the 30% aggregate-utilisation threshold), "
    "not a rupee cost/savings claim"
)


def naive_order(portfolio: Portfolio) -> list[str]:
    ranked = sorted(portfolio.debts, key=lambda d: (-d.stated_apr_pct, d.debt_id))
    return [d.debt_id for d in ranked]


def adjusted_order(adjusted_debts: list[AdjustedDebt]) -> list[str]:
    by_cost = sorted(
        adjusted_debts,
        key=lambda ad: (-ad.effective_cost_rank_input, ad.debt.debt_id),
    )
    crossing = [ad for ad in by_cost if ad.utilisation_priority_score > 0]
    non_crossing = [ad for ad in by_cost if ad.utilisation_priority_score <= 0]
    return [ad.debt.debt_id for ad in (crossing + non_crossing)]


def _own_mechanism(adjusted_debt: AdjustedDebt) -> DivergenceRationale | None:
    """This debt's OWN mechanism attribution, if it has one -- a real tax
    delta, fee delta, or utilisation-crossing score belonging to THIS debt.
    None means this debt's rank only moved because some OTHER debt's
    promotion displaced it, not because of any adjustment to itself (see
    compute_divergence_rationale, which handles that case)."""
    debt = adjusted_debt.debt
    tax_delta = debt.stated_apr_pct - adjusted_debt.after_tax_rate_pct
    fee_delta = adjusted_debt.foreclosure_adjusted_rate_pct - debt.stated_apr_pct
    has_tax = tax_delta > _EPSILON
    has_fee = fee_delta > _EPSILON
    has_utilisation = adjusted_debt.utilisation_priority_score > 0

    active = [name for name, flag in [("tax", has_tax), ("fee", has_fee), ("utilisation", has_utilisation)] if flag]
    if len(active) > 1:
        raise ValueError(
            f"debt {debt.debt_id!r} has more than one active mechanism at once ({active}) -- "
            f"compound divergence (e.g. a fixed-rate let-out home loan with both a tax and a "
            f"fee adjustment) is not yet supported by divergence attribution; this needs an "
            f"explicit design decision, not a silent pick of one mechanism over another"
        )
    if not active:
        return None

    if active[0] == "tax":
        return DivergenceRationale(
            mechanism=DivergenceMechanism.TAX,
            net_rupee_effect=tax_delta / 100 * debt.outstanding_balance,
        )
    if active[0] == "fee":
        return DivergenceRationale(
            mechanism=DivergenceMechanism.FEE,
            net_rupee_effect=-fee_delta / 100 * debt.outstanding_balance,
        )
    return DivergenceRationale(
        mechanism=DivergenceMechanism.UTILISATION,
        net_rupee_effect=0.0,
        traded_for=_UTILISATION_TRADED_FOR,
    )


def compute_divergence_rationale(
    divergence_points: list[str], adjusted_debts: list[AdjustedDebt]
) -> dict[str, DivergenceRationale]:
    """Every divergence point must be attributed to a mechanism -- see the
    module-level comment in schema.py above RepaymentOrdering for what each
    mechanism does and does not claim. A debt with no adjustment of its own
    (net_rupee_effect would be 0 either way) but whose rank still moved was
    "passively displaced": it borrows the mechanism of whichever OTHER
    divergent debt actively caused the displacement, keeping its own
    net_rupee_effect at 0.0 -- this project's samples are all simple
    pairwise swaps, so there is exactly one such cause; a portfolio where
    that isn't true raises rather than guessing which of several active
    mechanisms actually caused a given passive debt's shift.
    """
    by_id = {ad.debt.debt_id: ad for ad in adjusted_debts}
    own = {debt_id: _own_mechanism(by_id[debt_id]) for debt_id in divergence_points}

    rationale: dict[str, DivergenceRationale] = {}
    for debt_id in divergence_points:
        if own[debt_id] is not None:
            rationale[debt_id] = own[debt_id]
            continue

        causes = {other_id: r for other_id, r in own.items() if other_id != debt_id and r is not None}
        if len(causes) != 1:
            raise ValueError(
                f"debt {debt_id!r} diverged with no mechanism of its own, and there isn't "
                f"exactly one other divergent debt with an active mechanism to attribute it "
                f"to (found {len(causes)}: {sorted(causes)}) -- this needs an explicit design "
                f"decision for multi-cause divergence groups, not a guess"
            )
        [cause] = causes.values()
        rationale[debt_id] = DivergenceRationale(
            mechanism=cause.mechanism,
            net_rupee_effect=0.0,
            traded_for=_UTILISATION_TRADED_FOR if cause.mechanism == DivergenceMechanism.UTILISATION else None,
        )
    return rationale


def compute_ordering(portfolio: Portfolio, adjusted_debts: list[AdjustedDebt]) -> RepaymentOrdering:
    naive = naive_order(portfolio)
    adjusted = adjusted_order(adjusted_debts)
    naive_rank = {debt_id: i for i, debt_id in enumerate(naive)}
    adjusted_rank = {debt_id: i for i, debt_id in enumerate(adjusted)}
    divergence = [
        debt_id for debt_id in naive if naive_rank[debt_id] != adjusted_rank[debt_id]
    ]
    rationale = compute_divergence_rationale(divergence, adjusted_debts)
    return RepaymentOrdering(
        naive_order=naive,
        adjusted_order=adjusted,
        divergence_points=divergence,
        divergence_rationale=rationale,
    )
