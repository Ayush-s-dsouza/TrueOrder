"""Builds the eval manifest: PORTFOLIOS_PER_SEGMENT synthetic portfolios
per named segment (synth/segments.py), each stored with only enough
identifying data to regenerate its full ground truth on demand
(eval/ground_truth.py) -- the manifest is a source of test PORTFOLIOS, not
a store of computed answers, so there's a single place ground truth is ever
actually computed.

This is a genuine advantage over an extraction-style eval: ground truth
here is produced by TrueOrder's OWN deterministic core, not hand-verified
against a real external source (that verification burden already happened
once, for tax_rules.py/fee_rules.py's underlying legal/regulatory facts --
see DECISIONS.md). The uncertainty this eval exists to measure lives
entirely in explain.py's prose.

PORTFOLIOS_PER_SEGMENT is deliberately modest (see DECISIONS.md): each
explain() call takes 30-50 seconds on sarvam-105b's reasoning-heavy
latency profile (see explain.py), so manifest size directly sets how long
a full collection run takes, not just how it costs.

    python -m eval.manifest
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from adjust import adjust_portfolio
from eval.splits import assign_splits
from impact import compare_impact
from sequence import compute_ordering
from synth.generator import generate_portfolio
from synth.segments import SEGMENT_DESCRIPTIONS

MANIFEST_PATH = Path(__file__).parent / "manifest.json"

SEED = "trueorder-eval-2026-09-06"
PORTFOLIOS_PER_SEGMENT = 6
MONTHLY_SURPLUS = 15_000.0


def build_case(segment: str, index: int) -> dict:
    portfolio = generate_portfolio(SEED, segment, index)
    adjusted_debts = adjust_portfolio(portfolio)
    ordering = compute_ordering(portfolio, adjusted_debts)
    impact = compare_impact(portfolio, ordering, MONTHLY_SURPLUS)
    mechanisms = sorted({r.mechanism.value for r in ordering.divergence_rationale.values()})
    return {
        "case_id": f"{segment}_{index:03d}",
        "segment": segment,
        "index": index,
        "portfolio": portfolio.model_dump(mode="json"),
        "monthly_surplus": MONTHLY_SURPLUS,
        # Denormalized labels for quick manifest-level inspection only --
        # metrics.py always regenerates ground truth fresh from "portfolio"
        # via eval/ground_truth.py, never trusts these as scoring input.
        "has_divergence": bool(ordering.divergence_points),
        "mechanisms": mechanisms,
        "net_cost_delta": impact.net_cost_delta,
    }


def build_cases() -> list[dict]:
    return [
        build_case(segment, index)
        for segment in SEGMENT_DESCRIPTIONS
        for index in range(PORTFOLIOS_PER_SEGMENT)
    ]


def build_manifest() -> list[dict]:
    return assign_splits(build_cases(), group_keys=("segment",), value_key="index")


if __name__ == "__main__":
    manifest = build_manifest()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"wrote {len(manifest)} cases to {MANIFEST_PATH}")
    print(f"split counts: {dict(Counter(c['split'] for c in manifest))}")
    print(f"segment counts: {dict(Counter(c['segment'] for c in manifest))}")
    print(f"divergence counts: {dict(Counter(c['has_divergence'] for c in manifest))}")
    mechanism_counts: Counter = Counter()
    for c in manifest:
        mechanism_counts.update(c["mechanisms"])
    print(f"mechanism counts (cases with at least one divergence of that kind): {dict(mechanism_counts)}")
