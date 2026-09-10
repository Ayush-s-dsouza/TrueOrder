"""Makes 'no model call in the deterministic core' a checked fact, not a
docstring promise.

Three layers of check live here, deliberately, because each one can pass
while the other two fail:

1. STATIC, per-module (test_no_deterministic_core_module_imports_an_llm_sdk):
   AST-based, not a substring grep -- a commented-out import or a string
   that happens to mention an SDK name wouldn't trip this; an actual
   `import` statement naming a forbidden module will. Ported from Prequal's
   exact mechanism (see ../../Prequal/tests/test_no_llm_imports.py), fixing
   one latent issue found while porting it: Prequal's forbidden-roots set
   included the literal string "google.genai", which can never match
   because root-name matching always splits on "." first -- the fix here is
   to list "google" as the root instead.

2. STATIC, exclusivity (test_explain_is_the_only_project_file_that_imports_
   an_llm_sdk): the per-module check above only inspects a hand-maintained
   list, so a NEW file that calls a model would simply never be looked at.
   That test scans every project source file and asserts the set of files
   importing an SDK equals ALLOWED_LLM_MODULES exactly -- checked against
   the exemption list BY NAME, so adding a second model-calling file fails
   loudly instead of silently widening the exemption.

3. RUNTIME (test_deterministic_assess_path_makes_zero_llm_calls_at_the_sdk_
   boundary): static checks prove which modules import what, never what a
   given code path actually DOES at runtime. api.py is intentionally NOT in
   CHECKED_MODULES -- it may reach explain.py on the opt-in path (see
   DECISIONS.md) -- so "the deterministic path calls no model" is a claim
   only a runtime check can settle. That test replaces the SDK entry point
   itself with a counter and exercises the real /assess request.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api import app as api_app
from tests.test_api import _portfolio_payload

ROOT = Path(__file__).parent.parent

# explain.py is deliberately absent from this list -- it is the ONE module
# allowed to import an LLM SDK (see ALLOWED_LLM_MODULES below, which makes
# that exemption explicit and checkable rather than implied by omission).
# api.py is also absent, deliberately and for a different reason: it may
# reach explain.py on the explicit opt-in path, so its guarantee is a
# runtime one, enforced by the SDK-boundary test at the bottom of this file
# rather than by this static list. See DECISIONS.md.
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

# The complete, explicit exemption list: project source files permitted to
# import an LLM SDK. Paths are relative to the repo root, posix-style.
ALLOWED_LLM_MODULES = {"explain.py"}


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


def _project_source_files() -> list[Path]:
    """Every .py file this project ships as source: repo root, eval/, and
    synth/. tests/ is deliberately excluded -- a test legitimately needs to
    import or monkeypatch an SDK in order to prove things about it (this
    very file does), and scanning tests would make such a test impossible
    to write without tripping the check it exists to support."""
    files = sorted(ROOT.glob("*.py"))
    for package in ("eval", "synth"):
        files.extend(sorted((ROOT / package).glob("*.py")))
    return files


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


def test_explain_really_does_import_an_llm_sdk_positive_canary():
    """Confirms the checked-module list isn't accidentally excluding the
    one file that's SUPPOSED to import an LLM SDK -- a check with no
    positive case could pass by testing nothing. Ported from Prequal's
    equivalent canary for author_criterion.py. This proves explain.py DOES
    import one; the test below proves it's the ONLY file that does."""
    path = ROOT / "explain.py"
    assert path.exists()
    assert "sarvamai" in _imported_roots(path)


def test_explain_is_the_only_project_file_that_imports_an_llm_sdk():
    """Proves the exemption is EXCLUSIVE, checked against
    ALLOWED_LLM_MODULES by name rather than inferred from whichever files
    happen to import an SDK today.

    Why this matters beyond the per-module check above: CHECKED_MODULES is
    a hand-maintained list, so a newly added file that calls a model is not
    a violation of it -- it is simply invisible to it. Without this test,
    someone adding a second model-calling module would widen this project's
    'exactly one file talks to a model' guarantee silently, and every
    existing test would still pass. With it, that change fails loudly and
    forces an explicit decision to add the file to ALLOWED_LLM_MODULES.

    Same inverse-canary discipline as the google.genai fix documented at
    the top of this file: a check that can only ever confirm what is
    already true isn't a check."""
    importers = {
        path.relative_to(ROOT).as_posix()
        for path in _project_source_files()
        if _imported_roots(path) & FORBIDDEN_IMPORT_ROOTS
    }
    assert importers == ALLOWED_LLM_MODULES, (
        f"files importing an LLM SDK changed. Expected exactly "
        f"{sorted(ALLOWED_LLM_MODULES)}, found {sorted(importers)}. If a new file "
        f"legitimately needs to call a model, add it to ALLOWED_LLM_MODULES "
        f"deliberately -- do not delete this assertion."
    )


def _install_counting_fake_sdk(monkeypatch) -> dict[str, int]:
    """Replaces the Sarvam SDK entry point with a counter, so a test can
    assert on ACTUAL attempted SDK usage rather than on which modules are
    imported. Patching at the SDK boundary (`sarvamai.SarvamAI`) rather
    than at `explain.explain` is the point: it catches ANY route to a
    model, including one that bypassed explain.py entirely, which is
    exactly the failure a static import check cannot see."""
    counts = {"clients_constructed": 0, "completions_called": 0}

    class _FakeChat:
        def completions(self, **kwargs):
            counts["completions_called"] += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="fake explanation text"))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    class _FakeSarvamAI:
        def __init__(self, **kwargs):
            counts["clients_constructed"] += 1
            self.chat = _FakeChat()

    monkeypatch.setenv("SARVAM_API_KEY", "test-key-never-used-against-a-real-endpoint")
    monkeypatch.setattr("sarvamai.SarvamAI", _FakeSarvamAI)
    return counts


def test_deterministic_assess_path_makes_zero_llm_calls_at_the_sdk_boundary(monkeypatch):
    """The deterministic path (ADJUST -> SEQUENCE -> IMPACT, everything
    /assess does when `explain` is not requested) must reach no model at
    all -- proven by exercising the real request and counting attempted SDK
    usage at the boundary, not by asserting explain.py isn't imported by
    name.

    This is a genuinely different claim from the static checks above:
    explain.py exists, is importable, and IS imported elsewhere in this
    codebase (api.py's opt-in branch, eval/collect.py). Neither of those
    facts tells you whether a default /assess call touches a model. This
    does. The response assertions confirm the deterministic pipeline
    actually ran rather than short-circuiting, so a zero count can't be
    achieved by simply doing nothing."""
    counts = _install_counting_fake_sdk(monkeypatch)
    client = TestClient(api_app)

    response = client.post(
        "/assess",
        json={"portfolio": _portfolio_payload(), "monthly_surplus": 15_000.0, "explain": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ordering"]["adjusted_order"] == ["cc1", "pl1", "h1"]  # the real pipeline ran
    assert body["impact"]["net_cost_delta"] != 0  # IMPACT really simulated
    assert body["explanation"] is None
    assert counts == {"clients_constructed": 0, "completions_called": 0}


def test_the_zero_call_assertion_is_capable_of_failing(monkeypatch):
    """Inverse canary for the test above: the same counter, the same
    request, `explain: true` -- and it must register exactly one client
    construction and one completion call. Without this, a counter that was
    silently broken (never incrementing) would make the zero-call
    assertion above pass for the wrong reason, forever."""
    counts = _install_counting_fake_sdk(monkeypatch)
    client = TestClient(api_app)

    response = client.post(
        "/assess",
        json={"portfolio": _portfolio_payload(), "monthly_surplus": 15_000.0, "explain": True},
    )

    assert response.status_code == 200
    assert response.json()["explanation"] == "fake explanation text"
    assert counts == {"clients_constructed": 1, "completions_called": 1}
