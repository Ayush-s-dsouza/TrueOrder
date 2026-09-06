"""Loads the eval manifest by split. The test split is locked: it must not
be touched during collection or prompt-tuning iteration, only once at the
very end. This module is the single place that enforces that -- don't read
manifest.json directly if you want the lock to mean anything.

Ported near-verbatim from Prequal's eval/splits.py (see
../../Prequal/eval/splits.py) -- the mechanism is already fully generic;
only the grouping key changes (segment here, instead of
lender_id/field_id), since TrueOrder's manifest is grouped by synthetic
segment, not by real-world lender/field pairs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent

VALID_SPLITS = {"tune", "validation", "test"}


class TestSetLockedError(Exception):
    pass


def _manifest_path() -> Path:
    return BASE_DIR / "manifest.json"


def _test_access_log() -> Path:
    return BASE_DIR / "TEST_SET_ACCESS_LOG.jsonl"


def load_manifest() -> list[dict]:
    return json.loads(_manifest_path().read_text(encoding="utf-8"))


def load_split(split: str, allow_test: bool = False) -> list[dict]:
    """Returns all cases for one split.

    `split="test"` raises TestSetLockedError unless `allow_test=True` is
    passed explicitly (opened once, at the end) or the
    EVAL_ALLOW_TEST_SET=1 environment variable is set. Every successful
    test-set access is appended to TEST_SET_ACCESS_LOG.jsonl so it stays
    auditable -- this is meant to be opened once, not iterated against.
    """
    if split not in VALID_SPLITS:
        raise ValueError(f"split must be one of {VALID_SPLITS}, got {split!r}")

    if split == "test":
        env_override = os.environ.get("EVAL_ALLOW_TEST_SET") == "1"
        if not (allow_test or env_override):
            raise TestSetLockedError(
                "The test split is locked during collection and prompt-tuning. "
                "It may only be opened once, at the end, by calling "
                "load_split('test', allow_test=True)."
            )
        log_path = _test_access_log()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "via": "env" if env_override else "explicit"})
                + "\n"
            )

    return [case for case in load_manifest() if case["split"] == split]


def assign_splits(
    cases: list[dict],
    group_keys: tuple[str, ...] = ("segment",),
    value_key: str = "index",
    fracs: tuple[float, float, float] = (0.4, 0.3, 0.3),
    splits: tuple[str, str, str] = ("tune", "validation", "test"),
) -> list[dict]:
    """General stratified split assignment for any grid shape / repeat
    count. Mutates each case dict in place (adds "split"), and returns
    `cases`.

    Builds one repeating assignment cycle from `fracs` (e.g. (0.4,0.3,0.3)
    -> a 10-slot cycle: 4 tune, 3 validation, 3 test, interleaved as evenly
    as possible via largest-remainder allocation) and walks it per case at
    position `(value_index + group_index) % len(cycle)`. Rotating the
    starting phase by each group's index means no single segment is
    systematically stuck with the same slice of the cycle.
    """
    denom = 10
    target_counts = [round(f * denom) for f in fracs]
    if sum(target_counts) != denom:
        raise ValueError(f"fracs {fracs} must resolve to integer counts summing to {denom}")

    cycle: list[str] = []
    remaining = list(target_counts)
    progress = [0.0] * len(fracs)
    for _ in range(denom):
        progress = [p + f for p, f in zip(progress, fracs)]
        idx = max((i for i in range(len(fracs)) if remaining[i] > 0), key=lambda i: progress[i])
        cycle.append(splits[idx])
        progress[idx] -= 1.0
        remaining[idx] -= 1

    groups = sorted({tuple(case[k] for k in group_keys) for case in cases})
    group_index = {group: i for i, group in enumerate(groups)}

    for case in cases:
        group = tuple(case[k] for k in group_keys)
        position = (case[value_key] + group_index[group]) % denom
        case["split"] = cycle[position]

    return cases
