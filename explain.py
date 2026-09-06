"""The ONE file that calls a model. Turns the ADJUSTED plan's structured
output (Portfolio, AdjustedDebts, RepaymentOrdering, ImpactComparison) into
Dhruva-style conversational prose -- the same kind of answer a person gets
today when they ask an AI assistant "what order should I repay my debts
in?", except grounded entirely in numbers this project actually computed.

Provider-agnostic behind ExplanationProvider, mirroring Prequal's
author_criterion.py pattern exactly: swapping the model backing this
project is a config change (pass a different provider instance), not a
rewrite of explain() or anything that calls it. Only SarvamProvider is
implemented, per the same project-line precedent.

No other module in this project may import this file or an LLM SDK --
enforced by tests/test_no_llm_imports.py, which also carries a canary test
confirming THIS file really does import one (a check with no positive case
could pass by testing nothing).

This is the ONE place in the whole pipeline where hallucination risk
lives, and the discipline the SYSTEM_PROMPT enforces is this project's
central, hard-won finding (see DECISIONS.md, "'Adjusted = cheaper' was
never a valid blanket claim"): a divergence is never just "cheaper" or
"the better choice" -- it is one of three structurally different claims
(tax: a guaranteed rupee saving; fee: a ranking justification that is NOT
a savings guarantee; utilisation: explicitly NOT a rupee claim, a
credit-score trade-off), and stating the wrong KIND of claim -- calling a
utilisation promotion a "cost saving," for instance -- is a category
error, a worse failure than a wrong number. This is exactly what eval/
is built to measure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from schema import AdjustedDebt, ImpactComparison, Portfolio, RepaymentOrdering

SYSTEM_PROMPT = """You are explaining a personalized debt repayment plan to someone who asked "what order should I repay my loans and credit cards in?" -- the same kind of question people ask a financial chat assistant today. Write in clear, direct, conversational prose (second person, "you"), the way a knowledgeable friend would explain it, not a legal disclosure. No headers, no bullet-point spam -- flowing paragraphs are fine, but keep it tight enough to read in under a minute.

You will be given the COMPLETE computed output of a deterministic tax-and-fee-adjusted debt sequencing engine: every debt's balance, stated rate, after-tax rate, and fee-adjusted rate; the naive order (sorted by stated interest rate alone -- the way most tools and AI assistants answer this question today) and the adjusted order this engine recommends instead; every point where the two orders disagree, each already labeled with EXACTLY which of three mechanisms caused it; and a real simulated cost comparison between following each order.

Rules, followed exactly -- getting any of these wrong is worse than a rounding error, because it misrepresents what kind of claim is actually being made:

1. NEVER invent a rupee figure, a percentage, a debt name, or a month count that isn't given to you in the input. Every number in your explanation must be traceable to a number you were given.

2. State the adjusted order plainly as an explicit sequence naming every debt's ID in the order to repay them (for example "cc1, then cc2, then pl1"), and name the naive order the same explicit way too, so the person can see exactly where and how it differs from what a typical avalanche-only tool would tell them. A narrative description of what changed ("it swaps X and Y") is welcome IN ADDITION to the explicit sequence, never as a replacement for it -- the explicit sequence must appear somewhere in your answer.

3. For EVERY divergence point, you are told its mechanism -- "tax", "fee", or "utilisation". You must state the RIGHT KIND of claim for that mechanism -- never guess or default to calling something "cheaper" without checking which mechanism produced it:
   - mechanism="tax": this is a genuine, reliable rupee saving -- a real tax deduction lowers this debt's true cost. State it as a real saving, using the given net_rupee_effect and the note's detail (which regime, which property/loan condition it depends on).
   - mechanism="fee": this debt is genuinely more expensive than its stated interest rate suggests, because of a real foreclosure/prepayment charge. State that clearly, using the given numbers -- but do NOT promise this will save the person money overall. This is a reason the debt deserves more repayment priority than naive sorting gives it, not a savings guarantee -- a one-time charge doesn't behave like an ongoing rate, so whether prioritizing it actually saves money depends on the specific numbers (the simulated cost comparison you're given tells you which way it went for this portfolio -- say so honestly).
   - mechanism="utilisation": you are given a `traded_for` explanation stating this is a credit-score protection move, not a rupee-savings claim. You MUST convey that distinction explicitly -- say plainly that this promotion is about protecting the person's credit score (crossing a utilisation threshold), NOT about saving interest, and that it may cost a small amount of extra money as the price of that protection if the simulated numbers show that. Calling a utilisation-driven promotion a "cost saving" is the single most serious mistake you can make in this task.

4. If there are NO divergence points, say so directly: the naive and adjusted orders agree for this portfolio, and briefly explain why (no debt here has a live tax deduction, foreclosure charge, or utilisation-crossing situation).

5. When you mention the overall simulated cost comparison, state it as exactly what it is: the actual simulated rupee difference between following the two orders with the given monthly surplus for THIS portfolio, not a general promise. If it shows the adjusted order costing slightly more, say so plainly -- never hide, soften, or spin an unfavorable number, and never claim the adjusted order "saves money overall" when the numbers you were given say otherwise.

6. Never state or imply a tax deduction applies to a debt when its tax note says no deduction applies -- read every note you're given, and if it says a benefit does NOT apply (for example: a self-occupied home loan under the new tax regime, or an education loan under the new regime, or one past its 8-year window), say so plainly rather than glossing over it.

7. The FIRST time you refer to each debt, name its short ID in parentheses right after a natural description (for example "your home loan (h1)" or "your second credit card (cc2)") -- so someone cross-referencing this against their own accounts, or checking this explanation against the underlying numbers, can tell exactly which debt you mean. After that first mention, refer to it naturally however reads best.

Write one cohesive explanation covering: the two orders, every divergence with its correct mechanism-specific framing, and the overall simulated cost comparison."""


@dataclass(frozen=True)
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int


class ExplanationProvider(Protocol):
    name: str

    def complete(self, system_prompt: str, user_prompt: str) -> CompletionResult: ...


# Per-1M-token INR pricing for sarvam-105b, from
# https://docs.sarvam.ai/api/getting-started/pricing (retrieved 2026-09-06,
# same verification as Prequal's author_criterion.py, same model). Used
# only for the eval's cost-per-explanation report -- never for scoring or
# anything in the deterministic core.
SARVAM_105B_INPUT_INR_PER_MILLION = 29.28
SARVAM_105B_OUTPUT_INR_PER_MILLION = 73.2


class SarvamProvider:
    """The one concrete ExplanationProvider this project uses, matching
    Prequal's SarvamProvider exactly (see author_criterion.py) -- a second
    provider is a new class implementing the same two-method Protocol;
    explain() and every caller stay unchanged."""

    name = "sarvam-105b"

    def __init__(self, api_key: Optional[str] = None):
        from sarvamai import SarvamAI

        # sarvam-105b's reasoning-heavy latency (observed: single calls
        # taking 50+ seconds on this prompt, one timing out entirely at the
        # SDK's default) exceeds the client's default read timeout -- set
        # generously rather than retried, since a retry on a slow-but-
        # working request just doubles the wait.
        self._client = SarvamAI(api_subscription_key=api_key or os.environ["SARVAM_API_KEY"], timeout=180.0)

    def complete(self, system_prompt: str, user_prompt: str) -> CompletionResult:
        response = self._client.chat.completions(
            model="sarvam-105b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Generous on purpose, and more so than Prequal's own 4096:
            # sarvam-105b is a reasoning model whose chain-of-thought
            # (returned separately as message.reasoning_content) counts
            # against the same token budget as the final answer, and this
            # prompt's six-rule, per-mechanism-framing task is
            # reasoning-heavy. Observed directly during smoke-testing on
            # sample_002 (two divergence points, one mechanism each):
            # finish_reason="length" with message.content=None at both
            # 4096 and 8000; needed ~8712 completion tokens (~27,000 chars
            # of reasoning) to actually finish at max_tokens=20000. Set
            # well above that observed figure for headroom on portfolios
            # with more divergence points or mixed mechanisms, which would
            # need proportionally more per-mechanism reasoning.
            max_tokens=32_000,
        )
        text = response.choices[0].message.content
        usage = response.usage
        return CompletionResult(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


def estimate_cost_inr(result: CompletionResult) -> float:
    return (
        result.input_tokens / 1_000_000 * SARVAM_105B_INPUT_INR_PER_MILLION
        + result.output_tokens / 1_000_000 * SARVAM_105B_OUTPUT_INR_PER_MILLION
    )


def _format_debt_line(debt, adjusted_debt: AdjustedDebt) -> str:
    return (
        f"- {debt.debt_id} ({debt.debt_type.value}): balance Rs {debt.outstanding_balance:,.0f}, "
        f"stated APR {debt.stated_apr_pct:.2f}%, after-tax rate {adjusted_debt.after_tax_rate_pct:.2f}%, "
        f"fee-adjusted rate {adjusted_debt.foreclosure_adjusted_rate_pct:.2f}%, "
        f"utilisation_priority_score={adjusted_debt.utilisation_priority_score}\n"
        f"  tax note: {adjusted_debt.tax_adjustment_note}\n"
        f"  fee note: {adjusted_debt.fee_adjustment_note}"
    )


def _build_user_prompt(
    portfolio: Portfolio,
    adjusted_debts: list[AdjustedDebt],
    ordering: RepaymentOrdering,
    impact: ImpactComparison,
) -> str:
    by_id = {ad.debt.debt_id: ad for ad in adjusted_debts}
    lines: list[str] = [
        f"Borrower: {portfolio.borrower_id}, tax regime: {portfolio.tax_regime.value}, "
        f"marginal tax rate: {portfolio.marginal_tax_rate_pct}%",
        "",
        "Debts:",
    ]
    for debt in portfolio.debts:
        lines.append(_format_debt_line(debt, by_id[debt.debt_id]))
    lines += [
        "",
        f"Naive order (highest stated APR first): {ordering.naive_order}",
        f"Adjusted order (true effective cost first): {ordering.adjusted_order}",
        f"Divergence points: {ordering.divergence_points}",
    ]
    for debt_id, rationale in ordering.divergence_rationale.items():
        claim = (
            f"traded_for: {rationale.traded_for}"
            if rationale.traded_for is not None
            else f"net_rupee_effect/year: Rs {rationale.net_rupee_effect:,.2f}"
        )
        lines.append(f"  [{debt_id}] mechanism={rationale.mechanism.value}, {claim}")
    lines += [
        "",
        "Simulated impact (real month-by-month waterfall, both orders given the same monthly surplus):",
        (
            f"  naive: total_interest=Rs {impact.naive.total_interest_paid:,.2f}, "
            f"foreclosure_fees=Rs {impact.naive.total_foreclosure_fees_paid:,.2f}, "
            f"tax_benefit=Rs {impact.naive.total_tax_benefit_realized:,.2f}, "
            f"net_cost=Rs {impact.naive.net_cost:,.2f}, months_to_payoff={impact.naive.months_to_payoff}"
        ),
        (
            f"  adjusted: total_interest=Rs {impact.adjusted.total_interest_paid:,.2f}, "
            f"foreclosure_fees=Rs {impact.adjusted.total_foreclosure_fees_paid:,.2f}, "
            f"tax_benefit=Rs {impact.adjusted.total_tax_benefit_realized:,.2f}, "
            f"net_cost=Rs {impact.adjusted.net_cost:,.2f}, months_to_payoff={impact.adjusted.months_to_payoff}"
        ),
        f"  net_cost_delta (naive.net_cost - adjusted.net_cost): Rs {impact.net_cost_delta:,.2f}",
        "",
        "Write the explanation using ONLY the numbers and mechanisms above.",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class ExplanationResult:
    text: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_inr: float


def explain(
    portfolio: Portfolio,
    adjusted_debts: list[AdjustedDebt],
    ordering: RepaymentOrdering,
    impact: ImpactComparison,
    provider: Optional[ExplanationProvider] = None,
) -> ExplanationResult:
    provider = provider or SarvamProvider()
    user_prompt = _build_user_prompt(portfolio, adjusted_debts, ordering, impact)
    result = provider.complete(SYSTEM_PROMPT, user_prompt)
    if result.text is None:
        raise ValueError(
            "model returned no content (finish_reason was likely 'length' -- see "
            "SarvamProvider.complete's max_tokens comment)"
        )
    return ExplanationResult(
        text=result.text,
        provider=provider.name,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_inr=estimate_cost_inr(result),
    )
