"""Makes 'no model call in the deterministic core' a checked fact, not a
docstring promise. AST-based, not a substring grep -- a commented-out
import or a string that happens to mention an SDK name wouldn't trip this;
an actual `import` statement naming a forbidden module will. Ported from
Prequal's exact mechanism (see ../../Prequal/tests/test_no_llm_imports.py),
fixing one latent issue found while porting it: Prequal's forbidden-roots
set included the literal string "google.genai", which can never match
because root-name matching always splits on "." first -- the fix here is to
list "google" as the root instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent

# explain.py is deliberately absent from this list -- it is the ONE module
# allowed to import an LLM SDK. See
# test_explain_itself_is_the_only_file_allowed_to_import_an_llm_sdk below,
# which exists specifically so this list can't quietly exclude the one file
# that's SUPPOSED to import one, leaving this whole check testing nothing.
CHECKED_MODULES = [
    "schema.py",
    "tax_rules.py",
    "fee_rules.py",
    "profile.py",
    "adjust.py",
    "sequence.py",
    "impact.py",
]

FORBIDDEN_IMPORT_ROOTS = {"anthropic", "sarvamai", "openai", "google"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_no_deterministic_core_module_imports_an_llm_sdk():
    violations: dict[str, set[str]] = {}
    for filename in CHECKED_MODULES:
        path = ROOT / filename
        if not path.exists():
            continue
        found = _imported_roots(path) & FORBIDDEN_IMPORT_ROOTS
        if found:
            violations[filename] = found
    assert violations == {}, f"forbidden imports found: {violations}"


def test_explain_itself_is_the_only_file_allowed_to_import_an_llm_sdk():
    """Confirms the checked-module list isn't accidentally excluding the
    one file that's SUPPOSED to import an LLM SDK -- a check with no
    positive case could pass by testing nothing. Ported from Prequal's
    equivalent canary for author_criterion.py."""
    path = ROOT / "explain.py"
    assert path.exists()
    assert "sarvamai" in _imported_roots(path)
