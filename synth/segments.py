"""Named portfolio segments -- each one exists to exercise a specific
dimension of naive-vs-adjusted divergence (or, for AGREEMENT_CASE, the
deliberate absence of one). This mirrors Prequal's SEGMENTS registry, but
unlike Prequal's generic bureau-profile shapes (which vary only in
numeric ranges, independent of composition), each TrueOrder segment is
also a specific hand-chosen *composition* of debt types -- the divergence
each one is meant to demonstrate depends on which debt types are present,
not just their numbers. generator.py's per-segment builder functions are
the actual source of truth; this module documents *why* each one exists so
a reader doesn't have to reverse-engineer it from the numbers.
"""

from __future__ import annotations

SEGMENT_DESCRIPTIONS: dict[str, str] = {
    "agreement_case": (
        "All-unsecured portfolio (credit cards + a personal loan), no "
        "deductible debt, no near-threshold utilisation. Naive and adjusted "
        "orderings must be IDENTICAL -- the control case."
    ),
    "letout_home_old_regime": (
        "Old regime, let-out home loan. Should diverge on tax: the "
        "rental-income-bounded Section 24(b) deduction lowers the home "
        "loan's after-tax rate below where naive APR alone would rank it."
    ),
    "fixed_auto_foreclosure": (
        "Fixed-rate auto loan with a real foreclosure charge. Should "
        "diverge on fees: the foreclosure-adjusted rate raises the auto "
        "loan's effective cost above where naive APR alone would rank it."
    ),
    "utilisation_threshold": (
        "A credit card sitting just above the 30% aggregate-utilisation "
        "threshold. Should diverge on the heuristic: paying it off crosses "
        "the threshold, promoting it above a nominally higher-APR debt."
    ),
    "selfoccupied_new_regime_regression": (
        "New regime, self-occupied home loan. Must show ZERO tax "
        "adjustment -- the named regression test for the corrected "
        "'80E/24(b) regardless of regime' assumption (see DECISIONS.md)."
    ),
    "education_loan_80e_old_regime": (
        "Old regime, education loan inside its 8-year Section 80E window. "
        "The one case where a real deduction applies outside the home-loan "
        "machinery -- without this segment, 80E's activation path would "
        "only ever be exercised in tax_rules.py's own prose."
    ),
    "letout_home_old_regime_loss_capped": (
        "Same shape as letout_home_old_regime (let-out, old regime), but "
        "with a larger balance and lower rental income so the resulting "
        "loss exceeds the Rs 2,00,000 Section 71(3A) set-off cap. Sample 2 "
        "defines this cap branch but never triggers it (its loss stays "
        "under the cap); this segment is the one that actually exercises "
        "it -- deductible_fraction < 1.0 and a real carried-forward amount."
    ),
}
