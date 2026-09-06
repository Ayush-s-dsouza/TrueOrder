"""PROFILE stage: parse and validate a portfolio from JSON. All the actual
validation lives in schema.py's models -- this module is a thin loader, not
a second place for the same rules to be re-implemented (and drift out of
sync).
"""

from __future__ import annotations

import json
from pathlib import Path

from schema import Portfolio


def load_portfolio(path: str | Path) -> Portfolio:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Portfolio.model_validate(data)
