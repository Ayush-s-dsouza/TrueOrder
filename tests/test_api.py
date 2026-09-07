"""api.py tests. `explain=true` is tested via a monkeypatched explain()
-- never a real call here, matching this project's own stated discipline
(README: "pytest never [makes billed calls]"). Real explain() behavior is
covered by explain.py's own manual smoke tests and the eval, not here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def _portfolio_payload() -> dict:
    return {
        "borrower_id": "api_test",
        "tax_regime": "old",
        "marginal_tax_rate_pct": 30.0,
        "debts": [
            {
                "debt_id": "cc1",
                "debt_type": "credit_card",
                "outstanding_balance": 60_000,
                "stated_apr_pct": 42.0,
                "remaining_tenure_months": 360,
                "minimum_payment": 3_000,
                "current_utilisation_pct": 22.0,
                "aggregate_utilisation_pct": 22.0,
            },
            {
                "debt_id": "pl1",
                "debt_type": "personal_loan",
                "outstanding_balance": 250_000,
                "stated_apr_pct": 10.5,
                "remaining_tenure_months": 30,
                "minimum_payment": 9_000,
                "rate_type": "floating",
            },
            {
                "debt_id": "h1",
                "debt_type": "home_loan",
                "outstanding_balance": 4_000_000,
                "stated_apr_pct": 11.0,
                "remaining_tenure_months": 180,
                "minimum_payment": 45_000,
                "rate_type": "floating",
                "occupancy": "let_out",
                "annual_rental_income": 350_000,
            },
        ],
    }


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_assess_deterministic_only_matches_the_known_letout_home_divergence():
    """Same shape as the letout_home_old_regime segment (see
    tests/test_sequence.py) -- h1's tax shield should push it behind pl1
    in the adjusted order, with zero LLM calls (explain defaults False)."""
    response = client.post(
        "/assess",
        json={"portfolio": _portfolio_payload(), "monthly_surplus": 15_000.0, "explain": False},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["ordering"]["naive_order"] == ["cc1", "h1", "pl1"]
    assert body["ordering"]["adjusted_order"] == ["cc1", "pl1", "h1"]
    assert set(body["ordering"]["divergence_points"]) == {"h1", "pl1"}
    assert body["ordering"]["divergence_rationale"]["h1"]["mechanism"] == "tax"
    assert body["ordering"]["divergence_rationale"]["h1"]["net_rupee_effect"] > 0
    assert body["explanation"] is None


def test_assess_rejects_an_invalid_portfolio():
    """A floating-rate loan carrying a foreclosure charge must fail
    schema validation -- proves the API surfaces the same raise-on-
    violation guarantees as constructing the model directly, not a
    looser one at the request boundary."""
    payload = _portfolio_payload()
    payload["debts"][1]["rate_type"] = "floating"
    payload["debts"][1]["foreclosure_charge_pct"] = 2.0
    response = client.post("/assess", json={"portfolio": payload, "monthly_surplus": 15_000.0})
    assert response.status_code == 422


def test_assess_with_explain_true_calls_explain_and_returns_its_text(monkeypatch):
    calls = []

    def fake_explain(portfolio, adjusted_debts, ordering, impact, provider=None):
        calls.append((portfolio, adjusted_debts, ordering, impact))
        from explain import ExplanationResult

        return ExplanationResult(text="mocked explanation text", provider="mock", input_tokens=1, output_tokens=1, cost_inr=0.0)

    monkeypatch.setattr("explain.explain", fake_explain)

    response = client.post(
        "/assess",
        json={"portfolio": _portfolio_payload(), "monthly_surplus": 15_000.0, "explain": True},
    )
    assert response.status_code == 200
    assert response.json()["explanation"] == "mocked explanation text"
    assert len(calls) == 1


def test_assess_explain_false_never_imports_explain(monkeypatch):
    """Defensive check that the default path truly never reaches
    explain.py at all -- not just that it happens not to call it this
    time. If explain.explain is ever touched, this raises."""

    def boom(*args, **kwargs):
        raise AssertionError("explain() must not be called when explain=False")

    monkeypatch.setattr("explain.explain", boom)

    response = client.post(
        "/assess",
        json={"portfolio": _portfolio_payload(), "monthly_surplus": 15_000.0, "explain": False},
    )
    assert response.status_code == 200
