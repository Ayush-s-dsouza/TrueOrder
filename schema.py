"""Pydantic models for TrueOrder's deterministic core. Deliberately kept
free of any computation -- tax_rules.py, fee_rules.py, adjust.py, and
sequence.py own the logic; this module only owns the shape of the data and
the invariants that must hold for that data to be meaningful at all.

The validators here are the load-bearing part of this file, not the field
lists. Several of them exist specifically because a *missing* piece of
information (an unstated rental income, an unstated foreclosure charge) is
just as dangerous as a wrong one -- a debt that silently defaults to "no
adjustment" when the input was simply incomplete would look identical to a
debt that genuinely has no adjustment, and only a raising validator (not a
default value) can tell those two cases apart at construction time.

Organized into stage-banner sections mirroring the pipeline's own stage
order, per Prequal's convention, even though only PROFILE/ADJUST/SEQUENCE
stage models are consumed in this phase (IMPACT/EMIT stage models arrive in
the next phase).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

from fee_rules import UTILISATION_HEURISTIC_DISCLAIMER


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class DebtType(str, Enum):
    CREDIT_CARD = "credit_card"
    PERSONAL_LOAN = "personal_loan"
    HOME_LOAN = "home_loan"
    AUTO_LOAN = "auto_loan"
    EDUCATION_LOAN = "education_loan"


class TaxRegime(str, Enum):
    OLD = "old"
    NEW = "new"


class RateType(str, Enum):
    FLOATING = "floating"
    FIXED = "fixed"


class PropertyOccupancy(str, Enum):
    SELF_OCCUPIED = "self_occupied"
    LET_OUT = "let_out"


# ---------------------------------------------------------------------------
# PROFILE stage -- a portfolio's debts, as reported by the borrower
# ---------------------------------------------------------------------------


class DebtBase(BaseModel):
    """Fields every debt type carries, regardless of tax/fee treatment."""

    debt_id: str
    outstanding_balance: float = Field(gt=0)
    stated_apr_pct: float = Field(gt=0, le=100)
    remaining_tenure_months: int = Field(gt=0)
    minimum_payment: float = Field(ge=0)


class ForeclosureFieldsMixin(BaseModel):
    """Shared by every term-loan type that can carry a foreclosure charge
    (personal, home, auto -- not credit cards, which are revolving, and not
    education loans, which this project scopes to the tax dimension only,
    see DECISIONS.md). The validator raises rather than defaulting: a
    floating-rate loan reporting a charge, or a fixed-rate loan omitting
    one, is bad input that must be rejected at construction, not silently
    coerced into "no charge" or "no adjustment"."""

    rate_type: RateType
    foreclosure_charge_pct: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _foreclosure_charge_matches_rate_type(self) -> "ForeclosureFieldsMixin":
        if self.rate_type == RateType.FLOATING and self.foreclosure_charge_pct is not None:
            raise ValueError(
                "a floating-rate loan cannot carry a foreclosure_charge_pct -- RBI's "
                "floating-rate prohibition (see fee_rules.py) means no such charge "
                "can legally apply; a non-null value here means the input is wrong, "
                "not that the charge should be ignored"
            )
        if self.rate_type == RateType.FIXED and self.foreclosure_charge_pct is None:
            raise ValueError(
                "a fixed-rate loan must state its foreclosure_charge_pct explicitly "
                "-- RBI does not prohibit this charge for fixed-rate loans, so it "
                "cannot be assumed absent; supply the lender's actual figure"
            )
        return self


class CreditCard(DebtBase):
    debt_type: Literal[DebtType.CREDIT_CARD] = DebtType.CREDIT_CARD
    current_utilisation_pct: float = Field(ge=0, le=100)
    aggregate_utilisation_pct: float = Field(gt=0, le=100)


class PersonalLoan(DebtBase, ForeclosureFieldsMixin):
    debt_type: Literal[DebtType.PERSONAL_LOAN] = DebtType.PERSONAL_LOAN


class AutoLoan(DebtBase, ForeclosureFieldsMixin):
    debt_type: Literal[DebtType.AUTO_LOAN] = DebtType.AUTO_LOAN


class HomeLoan(DebtBase, ForeclosureFieldsMixin):
    debt_type: Literal[DebtType.HOME_LOAN] = DebtType.HOME_LOAN
    occupancy: PropertyOccupancy
    annual_rental_income: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _rental_income_matches_occupancy(self) -> "HomeLoan":
        if self.occupancy == PropertyOccupancy.LET_OUT and self.annual_rental_income is None:
            raise ValueError(
                "a let-out home loan must state annual_rental_income -- the "
                "Section 24(b) deduction for a let-out property depends on how "
                "much of the interest is absorbed by rental income (see "
                "tax_rules.py), so this cannot be assumed or defaulted"
            )
        if self.occupancy == PropertyOccupancy.SELF_OCCUPIED and self.annual_rental_income is not None:
            raise ValueError(
                "a self-occupied home loan cannot carry annual_rental_income -- a "
                "self-occupied property does not generate rental income by "
                "definition; a non-null value here means occupancy is misreported, "
                "not that the income should be ignored"
            )
        return self


class EducationLoan(DebtBase):
    debt_type: Literal[DebtType.EDUCATION_LOAN] = DebtType.EDUCATION_LOAN
    years_since_first_repayment: int = Field(ge=0)


Debt = Annotated[
    Union[CreditCard, PersonalLoan, HomeLoan, AutoLoan, EducationLoan],
    Field(discriminator="debt_type"),
]


class Portfolio(BaseModel):
    """`marginal_tax_rate_pct` is a required input, not derived from income
    slabs -- see DECISIONS.md for why computing India's actual slab system
    is out of scope. `tax_regime` has no default; a caller must state it
    explicitly, precisely because assuming a regime is the exact mistake
    this project exists to avoid."""

    borrower_id: str
    tax_regime: TaxRegime
    marginal_tax_rate_pct: float = Field(gt=0, le=100)
    debts: list[Debt] = Field(min_length=1)

    @model_validator(mode="after")
    def _debt_ids_unique(self) -> "Portfolio":
        ids = [d.debt_id for d in self.debts]
        if len(ids) != len(set(ids)):
            raise ValueError(f"debt_id values must be unique within a portfolio, got: {ids}")
        return self

    @model_validator(mode="after")
    def _credit_cards_agree_on_aggregate_utilisation(self) -> "Portfolio":
        cards = [d for d in self.debts if isinstance(d, CreditCard)]
        if len(cards) <= 1:
            return self
        values = {round(c.aggregate_utilisation_pct, 6) for c in cards}
        if len(values) > 1:
            raise ValueError(
                f"all credit cards in a portfolio must report the same "
                f"aggregate_utilisation_pct (it is a portfolio-wide figure, not a "
                f"per-card one) -- got disagreeing values: {sorted(values)}"
            )
        return self


# ---------------------------------------------------------------------------
# ADJUST stage -- after-tax/after-fee effective cost, per debt
# ---------------------------------------------------------------------------


class AdjustedDebt(BaseModel):
    """One debt's ADJUST-stage output. `tax_adjustment_note` and
    `fee_adjustment_note` are never blank, even when no adjustment applies
    -- an omitted note would be indistinguishable from a rule that was
    never checked, and this project's entire premise is that every
    adjustment (or deliberate non-adjustment) must be traceable to the rule
    that produced it."""

    debt: Debt
    after_tax_rate_pct: float
    tax_adjustment_note: str
    foreclosure_adjusted_rate_pct: float
    fee_adjustment_note: str
    utilisation_priority_score: float = 0.0
    effective_cost_rank_input: float


# ---------------------------------------------------------------------------
# SEQUENCE stage -- naive vs adjusted ordering
#
# THE PROJECT'S SINGLE MOST IMPORTANT DISTINCTION (see DECISIONS.md): the
# adjusted order is not one uniform "cheaper" or "optimal" claim. It
# resolves THREE separate, sometimes-conflicting objectives, and every
# divergence between naive and adjusted must be attributed to exactly one
# of them, with the right kind of claim attached:
#   - TAX:         a verified deduction lowers this debt's true cost.
#                  Mechanically cheaper, always, once realized -- BUT ONLY
#                  when the deductible fraction stays constant over the
#                  debt's life (see impact.py's tax-driven regression
#                  tests). When a rupee cap actively binds (e.g. interest
#                  exceeding rental income plus the Sec 71(3A) Rs 2L cap),
#                  the fraction improves as the balance amortizes down,
#                  and the real simulated outcome can go either way by a
#                  small margin -- see impact.py's capped-fraction
#                  correction, found by running the eval at scale, not
#                  assumed. net_rupee_effect > 0 whenever this mechanism
#                  fires either way; only the WATERFALL OUTCOME's
#                  guarantee is conditional, not this rupee figure itself.
#   - FEE:         a verified foreclosure charge raises this debt's true
#                  cost above its stated rate. Correctly identifies it as
#                  more expensive than naive assumes, but promoting it in
#                  a real waterfall can come out either cheaper OR
#                  slightly costlier overall than naive, because a
#                  one-time balance-proportional charge doesn't behave
#                  like a continuous rate (see impact.py). This is a
#                  RANKING JUSTIFICATION, not a savings guarantee.
#                  net_rupee_effect is negative when a real charge applies.
#   - UTILISATION: a heuristic override that protects a CIBIL score, not
#                  rupees. It is EXPLICITLY NOT a cost-savings claim --
#                  net_rupee_effect is always 0.0 by construction (ADJUST
#                  applies no rate change at all for this mechanism), and
#                  `traded_for` states the real, non-rupee reason instead.
#                  A small real rupee cost from this trade in a waterfall
#                  is the expected price of the trade, never a failure.
# Getting this wrong at the explanation layer -- stating a utilisation
# promotion as a "cost saving," for instance -- is a category error about
# what kind of claim is being made, worse than a wrong number, and is
# exactly what the eval (built later) is designed to catch.
# ---------------------------------------------------------------------------


class DivergenceMechanism(str, Enum):
    TAX = "tax"
    FEE = "fee"
    UTILISATION = "utilisation"


class DivergenceRationale(BaseModel):
    """One divergent debt's mechanism attribution -- see the module-level
    comment above for what each mechanism does and does not claim.
    `net_rupee_effect` is always an ANNUAL rupee figure computed directly
    from ADJUST-stage numbers (rate delta x outstanding balance), not a
    simulated waterfall outcome -- for the actual, realized cash effect of
    following the full adjusted order, see impact.py's ImpactComparison;
    this field explains WHY a debt was promoted, it does not substitute for
    IMPACT's answer to WHAT ACTUALLY HAPPENS."""

    mechanism: DivergenceMechanism
    net_rupee_effect: float
    traded_for: str | None = None

    @model_validator(mode="after")
    def _traded_for_only_for_utilisation(self) -> "DivergenceRationale":
        if self.mechanism == DivergenceMechanism.UTILISATION:
            if self.traded_for is None:
                raise ValueError(
                    "a utilisation-mechanism rationale must state what it traded rupees for "
                    "-- this is the one mechanism that is explicitly not a cost-savings claim, "
                    "and that must never be left implicit"
                )
        elif self.traded_for is not None:
            raise ValueError(
                f"traded_for is only meaningful for the utilisation mechanism (it exists to "
                f"flag a non-rupee trade-off); a {self.mechanism.value} rationale is a rupee "
                f"claim on its own and must not carry one"
            )
        return self


class RepaymentOrdering(BaseModel):
    """`divergence_rationale` has exactly one entry per debt_id in
    `divergence_points` -- every divergence must be attributed to a
    mechanism, never left as a bare rank change with no stated reason."""

    naive_order: list[str]
    adjusted_order: list[str]
    divergence_points: list[str]
    divergence_rationale: dict[str, DivergenceRationale] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _rationale_matches_divergence_points(self) -> "RepaymentOrdering":
        if set(self.divergence_rationale) != set(self.divergence_points):
            raise ValueError(
                f"divergence_rationale must have exactly one entry per divergence point -- "
                f"divergence_points={sorted(self.divergence_points)}, "
                f"divergence_rationale keys={sorted(self.divergence_rationale)}"
            )
        return self


# ---------------------------------------------------------------------------
# IMPACT stage -- what a given repayment order actually costs, simulated
# month by month rather than assumed. `net_cost` is the true economic
# comparison this project is built around: nominal interest actually
# accrued at the STATED rate (that's what a lender contractually charges,
# regardless of any tax/fee adjustment used for ranking), plus one-time
# foreclosure fees actually triggered, minus tax benefit actually realized
# year by year while the debt remains outstanding.
# ---------------------------------------------------------------------------


class ImpactResult(BaseModel):
    total_interest_paid: float
    total_foreclosure_fees_paid: float
    total_tax_benefit_realized: float
    net_cost: float
    months_to_payoff: int


class ImpactComparison(BaseModel):
    """`net_cost_delta` is naive.net_cost - adjusted.net_cost: positive
    means the adjusted order is cheaper in real rupees, not just
    differently ranked."""

    naive: ImpactResult
    adjusted: ImpactResult
    net_cost_delta: float


# ---------------------------------------------------------------------------
# Schema-pinned disclaimers -- a Literal[CONSTANT_STRING] field makes these
# impossible to omit or reword without failing validation, the same
# guarantee Prequal used for its calibration disclaimer.
# ---------------------------------------------------------------------------

RULES_VERIFIED_DATE = "2026-09-06"

RULES_CURRENCY_DISCLAIMER = (
    f"Tax and fee rules encoded in this system were verified via web search "
    f"on {RULES_VERIFIED_DATE} and are current as of that date. They are "
    f"subject to change by a future Finance Act or RBI circular."
)


class RulesCurrencyDisclaimer(BaseModel):
    statement: Literal[RULES_CURRENCY_DISCLAIMER] = RULES_CURRENCY_DISCLAIMER


class UtilisationHeuristicDisclaimer(BaseModel):
    statement: Literal[UTILISATION_HEURISTIC_DISCLAIMER] = UTILISATION_HEURISTIC_DISCLAIMER
