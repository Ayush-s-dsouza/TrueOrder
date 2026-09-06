"""Computes eval metrics from a raw results log + eval/manifest.json.

This eval measures faithfulness at the ONE place genuine uncertainty lives
in this project: explain.py's prose. Ground truth is computed by
TrueOrder's own deterministic core (eval/ground_truth.py), not hand-
verified against an external source -- so every check here is a direct
comparison against a number or label this project itself already computed
and trusts.

Per DECISIONS.md's central finding, the headline risk is NOT "the model
got a number wrong" -- it's a CATEGORY ERROR: stating a utilisation-driven
promotion as a cost saving, or a fee-driven one as a savings guarantee,
misrepresents what KIND of claim is being made, and is worse than a wrong
number because it looks completely plausible while answering a different
question than the one asked. `mechanism_framing_correct` targets exactly
that, and FAITHFULNESS_RATE (every applicable check passing at once) is
the headline metric this eval reports.

These are text heuristics, not a model-graded judgment -- documented
explicitly where a check is necessary-but-not-sufficient (e.g.
`utilisation_correctly_framed` proves the right VOCABULARY appears, not
that no contradicting claim exists elsewhere in the same explanation). A
model-graded judge would close that gap; it's out of scope for this phase,
named here rather than silently assumed away.

    python -m eval.metrics --experiment baseline
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Optional

from eval.ground_truth import CaseGroundTruth, ground_truth_for_case
from eval.splits import load_manifest
from explain import _build_user_prompt
from schema import DivergenceMechanism

RESULTS_DIR = Path(__file__).parent / "results"

NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")
SAVINGS_LANGUAGE_PATTERN = re.compile(r"\bsav(?:e|es|ed|ing)\b|\bcheaper\b|\blower\s+(?:net\s+)?cost\b", re.IGNORECASE)
COSTLIER_ADMISSION_PATTERN = re.compile(
    # "cost(s) ... more" allows a short character span between them ("costs
    # slightly more", "costs about Rs 1,417.93 more") -- real bug found via
    # eval collection: a genuinely correct, honest admission was missed
    # twice over. First with a word-gap version of this pattern that
    # required "cost" and "more" adjacent (or one "you" apart): missed
    # "costs slightly more". Fixing that to a word-count gap STILL missed
    # "costs about Rs 1,417.93 more" and "costs you Rs 297.11 more",
    # because a rupee figure's "." and "," aren't \w characters, so a
    # word-boundary-based token count silently undercounts them. A
    # character-based gap sidesteps punctuation entirely (see DECISIONS.md).
    r"cost(?:s|ing)?\s+.{0,30}?\bmore\b|more expensive|costlier|does\s+not\s+come\s+for\s+free|"
    r"higher\s+(?:net\s+)?cost|extra\s+(?:rupee|cost|money)",
    re.IGNORECASE,
)
CREDIT_SCORE_LANGUAGE_PATTERN = re.compile(r"credit score|cibil|utilisation|utilization", re.IGNORECASE)
NO_DIVERGENCE_LANGUAGE_PATTERN = re.compile(r"\bagree\b|\bsame\b|\bidentical\b|\bno\s+(?:difference|divergence)\b", re.IGNORECASE)
BLOCKED_TAX_NOTE_MARKERS = ("no deduction applies", "fully blocked")
FALSE_TAX_CLAIM_PATTERN = re.compile(r"tax\s+(?:benefit|saving|savings|deduction|shield)", re.IGNORECASE)
# A claim-pattern match preceded by one of these within NEGATION_WINDOW
# characters is a correct denial ("does not qualify for a ... deduction"),
# not a false claim -- without this, "there are no tax deductions" matches
# the claim pattern on its "tax deduction" substring and gets flagged as a
# fabricated benefit, exactly backwards. Confirmed against a real collected
# explanation during eval development (see DECISIONS.md).
NEGATION_CUES = ("no ", "not ", "n't", "without", "never", "doesn't", "does not", "isn't", "aren't")
NEGATION_WINDOW = 40


def _is_negated(text: str, match_start: int, window: int = NEGATION_WINDOW) -> bool:
    preceding = text[max(0, match_start - window) : match_start].lower()
    return any(cue in preceding for cue in NEGATION_CUES)


def load_results(experiment: str, results_dir: Optional[Path] = None) -> list[dict]:
    path = (results_dir or RESULTS_DIR) / f"{experiment}.jsonl"
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def join_with_manifest(results: list[dict]) -> list[dict]:
    manifest_by_id = {c["case_id"]: c for c in load_manifest()}
    joined = []
    for r in results:
        case = manifest_by_id.get(r["case_id"])
        if case is None:
            continue
        joined.append({**r, "_case": case})
    return joined


def _extract_numbers(text: str) -> list[float]:
    out = []
    for match in NUMBER_PATTERN.finditer(text):
        cleaned = match.group().replace(",", "")
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


def _numbers_match(a: float, allowed: list[float]) -> bool:
    """Compares by ABSOLUTE VALUE, not signed value -- a net_cost_delta of
    -949.66 (naive.net_cost - adjusted.net_cost) is routinely, correctly
    restated in natural prose with the opposite sign framing ("the
    adjusted order costs Rs 949.66 more"), and that is a faithful
    restatement, not an invented number. Confirmed against a real
    collected explanation during eval development: flagging the
    magnitude-only restatement as fabricated was a false positive in this
    check, not a real model error (see DECISIONS.md)."""
    tolerance = max(1.0, abs(a) * 0.01)
    return any(abs(abs(a) - abs(b)) <= tolerance for b in allowed)


def _debt_text_window(text: str, debt_id: str, all_debt_ids: list[str]) -> str:
    """The prose window attributable to one debt: from its first literal
    mention to the next OTHER debt's first mention (or end of text). A
    coarse approximation -- prose isn't guaranteed to segment this cleanly
    -- but explain.py's SYSTEM_PROMPT requires each debt's ID to appear on
    first mention specifically so this kind of check is tractable."""
    idx = text.find(debt_id)
    if idx == -1:
        return ""
    next_indices = [text.find(other, idx + len(debt_id)) for other in all_debt_ids if other != debt_id]
    next_indices = [i for i in next_indices if i != -1]
    end = min(next_indices) if next_indices else len(text)
    return text[idx:end]


def all_debts_mentioned(text: str, gt: CaseGroundTruth) -> bool:
    return all(debt.debt_id in text for debt in gt.portfolio.debts)


SEQUENCE_MAX_GAP = 80


def _debt_id_occurrence_sequence(text: str, all_ids: list[str]) -> list[tuple[int, str]]:
    occurrences: list[tuple[int, str]] = []
    for debt_id in all_ids:
        start = 0
        while True:
            idx = text.find(debt_id, start)
            if idx == -1:
                break
            occurrences.append((idx, debt_id))
            start = idx + len(debt_id)
    occurrences.sort()
    # Collapse immediately-repeated mentions of the same debt into one slot
    # (e.g. "cc1 ... your credit card (cc1) again" shouldn't count as two
    # slots in a sequence listing).
    collapsed: list[tuple[int, str]] = []
    for pos, debt_id in occurrences:
        if collapsed and collapsed[-1][1] == debt_id:
            continue
        collapsed.append((pos, debt_id))
    return collapsed


def adjusted_order_sequence_correct(text: str, gt: CaseGroundTruth) -> Optional[bool]:
    """None if not every debt is mentioned (order isn't verifiable then --
    see all_debts_mentioned, a separate, required check).

    Looks for `adjusted_order`'s exact debt-ID sequence as a TIGHT,
    CONTIGUOUS run anywhere in the text (each id within SEQUENCE_MAX_GAP
    characters of the previous one) -- deliberately independent of any
    label phrase like "adjusted order". Real collected explanations during
    eval development used "adjusted plan", led with the recommendation
    before any label at all, or restated the sequence as a bare "X, then
    Y, then Z" list -- a marker-phrase anchor missed all of these even
    though the sequence itself was stated correctly (see DECISIONS.md).
    This can't be fooled by the NAIVE order's different sequence, since it
    only matches windows equal to `adjusted_order` exactly; on a portfolio
    with no divergence the two sequences are identical anyway, so either
    reading is correct."""
    if not all_debts_mentioned(text, gt):
        return None
    order = gt.ordering.adjusted_order
    seq = _debt_id_occurrence_sequence(text, [d.debt_id for d in gt.portfolio.debts])
    n = len(order)
    for i in range(len(seq) - n + 1):
        window = seq[i : i + n]
        if [debt_id for _, debt_id in window] != order:
            continue
        if all(window[j + 1][0] - window[j][0] <= SEQUENCE_MAX_GAP for j in range(n - 1)):
            return True
    return False


def _derived_impact_deltas(gt: CaseGroundTruth) -> list[float]:
    """A model that shows its work legitimately subtracts naive from
    adjusted for the impact sub-components (e.g. "the adjusted path incurs
    Rs 1,951.23 more in interest even though it trims foreclosure fees by
    Rs 60.15") -- real, correct arithmetic on numbers actually given, not
    a fabrication. Found via eval collection: a genuinely correct
    explanation was flagged as inventing two numbers that were exactly
    these two deltas (see DECISIONS.md). Narrowly allowing just these
    three specific, predictable sub-component deltas (not an open-ended
    "any two numbers may be subtracted" rule, which would make this check
    nearly meaningless) closes that gap without loosening the check
    against an actually novel, unexplained number."""
    return [
        abs(gt.impact.adjusted.total_interest_paid - gt.impact.naive.total_interest_paid),
        abs(gt.impact.adjusted.total_foreclosure_fees_paid - gt.impact.naive.total_foreclosure_fees_paid),
        abs(gt.impact.adjusted.total_tax_benefit_realized - gt.impact.naive.total_tax_benefit_realized),
    ]


def no_invented_numbers(text: str, gt: CaseGroundTruth) -> tuple[bool, int]:
    """Returns (passed, invented_count). "Allowed" numbers are every number
    that appears anywhere in the exact prompt explain.py actually sent
    (structured fields AND note text both, so a legitimate figure quoted
    from a tax/fee note -- a statute cap, a section number -- is never a
    false positive) plus the three impact sub-component deltas a model may
    legitimately derive (see _derived_impact_deltas). A genuinely
    fabricated rupee figure is still caught."""
    prompt_text = _build_user_prompt(gt.portfolio, gt.adjusted_debts, gt.ordering, gt.impact)
    allowed = _extract_numbers(prompt_text) + _derived_impact_deltas(gt)
    found = _extract_numbers(text)
    invented = [n for n in found if not _numbers_match(n, allowed)]
    return len(invented) == 0, len(invented)


def cost_direction_correctly_stated(text: str, gt: CaseGroundTruth) -> bool:
    """When net_cost_delta is exactly 0, no directional claim is required
    either way (the no-divergence check covers the agreement case
    separately). When nonzero, the RIGHT direction must be acknowledged --
    favorable language when adjusted is genuinely cheaper, an explicit
    admission when it is genuinely costlier. This is what actually
    operationalizes "never hide, soften, or spin an unfavorable number.\""""
    delta = gt.impact.net_cost_delta
    if abs(delta) < 1e-6:
        return True
    if delta > 0:
        return bool(SAVINGS_LANGUAGE_PATTERN.search(text))
    return bool(COSTLIER_ADMISSION_PATTERN.search(text))


def utilisation_correctly_framed(text: str, gt: CaseGroundTruth) -> Optional[bool]:
    """None if this case has no utilisation-mechanism divergence at all.
    NECESSARY, NOT SUFFICIENT: proves the right vocabulary (credit score /
    CIBIL / utilisation) appears somewhere in the explanation when it's
    required to. Does not prove the explanation never ALSO makes a
    contradicting cost-saving claim about that specific debt elsewhere --
    a model-graded judge would be needed to close that gap; not built this
    phase."""
    has_utilisation = any(
        r.mechanism == DivergenceMechanism.UTILISATION for r in gt.ordering.divergence_rationale.values()
    )
    if not has_utilisation:
        return None
    return bool(CREDIT_SCORE_LANGUAGE_PATTERN.search(text))


def no_divergence_correctly_stated(text: str, gt: CaseGroundTruth) -> Optional[bool]:
    """None if this case DOES have a divergence (not applicable)."""
    if gt.ordering.divergence_points:
        return None
    return bool(NO_DIVERGENCE_LANGUAGE_PATTERN.search(text))


def no_false_tax_claim_for_blocked_debts(text: str, gt: CaseGroundTruth) -> Optional[bool]:
    """None if no debt in this case has a blocked/zero tax adjustment. This
    is the direct check for the exact failure mode this project's research
    phase found and corrected (see DECISIONS.md): claiming a tax benefit
    for a self-occupied home loan under the new regime, or an education
    loan past its window or under the new regime."""
    all_ids = [d.debt_id for d in gt.portfolio.debts]
    blocked_debt_ids = [
        ad.debt.debt_id for ad in gt.adjusted_debts if any(m in ad.tax_adjustment_note.lower() for m in BLOCKED_TAX_NOTE_MARKERS)
    ]
    if not blocked_debt_ids:
        return None
    for debt_id in blocked_debt_ids:
        window = _debt_text_window(text, debt_id, all_ids)
        for match in FALSE_TAX_CLAIM_PATTERN.finditer(window):
            if not _is_negated(window, match.start()):
                return False
    return True


def score_row(row: dict) -> dict:
    """Computes every applicable check for one collected row. A check
    returns None (not applicable) rather than True when its precondition
    isn't met (e.g. no utilisation divergence in this case) -- None is
    excluded from that check's own rate AND from is_faithful, so a case
    that never exercises a mechanism can't inflate that mechanism's
    apparent correctness."""
    case = row["_case"]
    gt = ground_truth_for_case(case)
    text = row.get("explanation_text") or ""

    invented_ok, invented_count = no_invented_numbers(text, gt)
    checks = {
        "all_debts_mentioned": all_debts_mentioned(text, gt),
        "order_correct": adjusted_order_sequence_correct(text, gt),
        "no_invented_numbers": invented_ok,
        "invented_number_count": invented_count,
        "cost_direction_correct": cost_direction_correctly_stated(text, gt),
        "utilisation_correctly_framed": utilisation_correctly_framed(text, gt),
        "no_divergence_correctly_stated": no_divergence_correctly_stated(text, gt),
        "no_false_tax_claim_for_blocked_debts": no_false_tax_claim_for_blocked_debts(text, gt),
    }
    required = [
        checks["all_debts_mentioned"],
        checks["order_correct"],
        checks["no_invented_numbers"],
        checks["cost_direction_correct"],
        checks["utilisation_correctly_framed"],
        checks["no_divergence_correctly_stated"],
        checks["no_false_tax_claim_for_blocked_debts"],
    ]
    applicable = [c for c in required if c is not None]
    checks["is_faithful"] = all(applicable) if applicable else True
    return checks


def compute_metrics(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    errored = [r for r in rows if r.get("error")]
    usable = [r for r in rows if not r.get("error")]

    scored = [{**r, **score_row(r)} for r in usable]

    def rate(key: str) -> Optional[float]:
        applicable = [r[key] for r in scored if r[key] is not None]
        return sum(1 for v in applicable if v) / len(applicable) if applicable else None

    def count_applicable(key: str) -> int:
        return sum(1 for r in scored if r[key] is not None)

    metrics: dict[str, Any] = {
        "total_rows": n,
        "errored_rows": len(errored),
        "usable_rows": len(usable),
    }
    for key in (
        "all_debts_mentioned",
        "order_correct",
        "no_invented_numbers",
        "cost_direction_correct",
        "utilisation_correctly_framed",
        "no_divergence_correctly_stated",
        "no_false_tax_claim_for_blocked_debts",
        "is_faithful",
    ):
        metrics[f"{key}_rate"] = rate(key)
        metrics[f"{key}_applicable_count"] = count_applicable(key)

    metrics["total_invented_numbers"] = sum(r["invented_number_count"] for r in scored)

    # Repeat consistency: for each case_id, do all repeats agree on
    # is_faithful? A case that's faithful on one run and not on another is
    # a reliability problem the headline rate alone would hide.
    by_case: dict[str, list[dict]] = {}
    for r in scored:
        by_case.setdefault(r["case_id"], []).append(r)
    non_unanimous = sum(1 for rows_ in by_case.values() if len({r["is_faithful"] for r in rows_}) > 1)
    metrics["cases_total"] = len(by_case)
    metrics["cases_non_unanimous_on_faithfulness"] = non_unanimous
    metrics["non_unanimous_rate"] = non_unanimous / len(by_case) if by_case else None

    total_cost = sum(r.get("cost_inr", 0.0) for r in usable)
    metrics["total_cost_inr"] = round(total_cost, 4)
    metrics["cost_per_explanation_inr"] = round(total_cost / len(usable), 4) if usable else None

    return metrics


def print_report(metrics: dict[str, Any]) -> None:
    print(f"Total rows: {metrics['total_rows']}  (usable: {metrics['usable_rows']}, errored: {metrics['errored_rows']})")
    print()
    print(f"FAITHFULNESS RATE (headline): {metrics['is_faithful_rate']:.1%}" if metrics["is_faithful_rate"] is not None else "FAITHFULNESS RATE: n/a")
    print()
    print("Per-check rates (None/not-applicable rows excluded from each):")
    for key in (
        "all_debts_mentioned",
        "order_correct",
        "no_invented_numbers",
        "cost_direction_correct",
        "utilisation_correctly_framed",
        "no_divergence_correctly_stated",
        "no_false_tax_claim_for_blocked_debts",
    ):
        r = metrics[f"{key}_rate"]
        n = metrics[f"{key}_applicable_count"]
        print(f"  {key}: {r:.1%} (n={n})" if r is not None else f"  {key}: n/a (n=0)")
    print()
    print(f"Total invented numbers across all rows: {metrics['total_invented_numbers']}")
    print()
    if metrics["non_unanimous_rate"] is not None:
        print(
            f"Repeat consistency: {metrics['cases_non_unanimous_on_faithfulness']}/{metrics['cases_total']} cases "
            f"non-unanimous on faithfulness across repeats ({metrics['non_unanimous_rate']:.1%})"
        )
    print()
    if metrics.get("cost_per_explanation_inr") is not None:
        print(f"Total cost: Rs.{metrics['total_cost_inr']:.4f}  ({metrics['cost_per_explanation_inr']:.4f}/explanation)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", required=True)
    args = parser.parse_args()

    results = load_results(args.experiment)
    rows = join_with_manifest(results)
    computed = compute_metrics(rows)
    print_report(computed)
