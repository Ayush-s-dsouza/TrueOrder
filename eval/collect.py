"""Runs eval cases against the real Sarvam API (via explain.py) and logs
each explanation's raw text plus usage/cost. Resumable: skips
(case_id, run_index) pairs already logged with no error, so an interrupted
run can continue without repeating (and re-paying for) completed calls.

Each call costs real money and takes real time (30-50s on sarvam-105b's
reasoning-heavy latency profile, see explain.py) -- this is not a free
loop to run repeatedly out of curiosity.

    python -m eval.collect --experiment baseline --split tune validation --repeats 2
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from eval.ground_truth import ground_truth_for_case
from eval.splits import load_split
from explain import explain

RESULTS_DIR = Path(__file__).parent / "results"


def run_case_once(case: dict, run_index: int, experiment: str) -> dict:
    record: dict = {
        "experiment": experiment,
        "case_id": case["case_id"],
        "run_index": run_index,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        ground_truth = ground_truth_for_case(case)
        result = explain(
            ground_truth.portfolio,
            ground_truth.adjusted_debts,
            ground_truth.ordering,
            ground_truth.impact,
        )
        record.update(
            explanation_text=result.text,
            provider=result.provider,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_inr=result.cost_inr,
            error=None,
        )
    except Exception as e:  # noqa: BLE001 -- data-collection loop: log and continue
        record.update(
            explanation_text=None,
            provider=None,
            input_tokens=0,
            output_tokens=0,
            cost_inr=0.0,
            error=f"{type(e).__name__}: {e}",
        )
    return record


def load_already_done(out_path: Path) -> set[tuple[str, int]]:
    if not out_path.exists():
        return set()
    done = set()
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("error"):
                continue  # failed attempts must be retried, not skipped
            done.add((row["case_id"], row["run_index"]))
    return done


def run_experiment(cases: list[dict], experiment: str, n_repeats: int = 2, out_path: Optional[Path] = None) -> Path:
    load_dotenv()
    out_path = out_path or (RESULTS_DIR / f"{experiment}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    already_done = load_already_done(out_path)

    total = len(cases) * n_repeats
    done_count = 0
    with out_path.open("a", encoding="utf-8") as f:
        for case in cases:
            for run_index in range(n_repeats):
                done_count += 1
                if (case["case_id"], run_index) in already_done:
                    continue
                record = run_case_once(case, run_index, experiment)
                f.write(json.dumps(record) + "\n")
                f.flush()
                status = "error" if record.get("error") else "ok"
                print(
                    f"[{done_count}/{total}] {case['case_id']} run={run_index} {status} "
                    f"cost=Rs.{record.get('cost_inr', 0):.4f} {record.get('error') or ''}"
                )
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--split", nargs="+", default=["tune", "validation"])
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()

    all_cases: list[dict] = []
    for split in args.split:
        all_cases.extend(load_split(split))

    result_path = run_experiment(all_cases, args.experiment, args.repeats)
    print(f"done -- results in {result_path}")
