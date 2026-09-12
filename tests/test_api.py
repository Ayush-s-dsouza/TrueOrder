"""api.py tests. `explain=true` is tested via a monkeypatched explain()
-- never a real call here, matching this project's own stated discipline
(README: "pytest never [makes billed calls]"). Real explain() behavior is
covered by explain.py's own manual smoke tests and the eval, not here.
"""

from __future__ import annotations

import pytest
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


def _with_debt_field(debt_index: int, field: str, value):
    """A valid payload with exactly one numeric field pushed out of range."""
    payload = _portfolio_payload()
    payload["debts"][debt_index][field] = value
    return payload


@pytest.mark.parametrize(
    "field,value,why",
    [
        ("outstanding_balance", 0, "a zero-balance debt is not a debt"),
        ("outstanding_balance", -5_000, "negative balance"),
        ("stated_apr_pct", 0, "a 0% debt has no cost to rank"),
        ("stated_apr_pct", -5, "negative rate"),
        ("stated_apr_pct", 150, "rate above 100%"),
        ("remaining_tenure_months", 0, "zero tenure"),
        ("remaining_tenure_months", -12, "negative tenure"),
        ("minimum_payment", -1_000, "negative minimum payment"),
    ],
)
def test_assess_rejects_out_of_range_numeric_fields_on_every_debt(field, value, why):
    """Sweeps the shared DebtBase numerics through the real API surface.
    These were already constrained in schema.py, but "the model enforces
    it" and "the endpoint enforces it" are different claims -- this proves
    the constraint is actually reachable through /assess rather than
    bypassed by the request-parsing path."""
    response = client.post(
        "/assess",
        json={"portfolio": _with_debt_field(1, field, value), "monthly_surplus": 15_000.0},
    )
    assert response.status_code == 422, f"expected 422 for {field}={value} ({why})"


@pytest.mark.parametrize(
    "field,value",
    [("current_utilisation_pct", -1), ("current_utilisation_pct", 101),
     ("aggregate_utilisation_pct", 0), ("aggregate_utilisation_pct", 101)],
)
def test_assess_rejects_out_of_range_credit_card_utilisation(field, value):
    """aggregate_utilisation_pct must be strictly > 0 specifically because
    adjust.py divides by it to derive the portfolio's total credit limit --
    a zero there would be a ZeroDivisionError, not a wrong answer."""
    response = client.post(
        "/assess",
        json={"portfolio": _with_debt_field(0, field, value), "monthly_surplus": 15_000.0},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("value", [-5, 0, 101, 150])
def test_assess_rejects_out_of_range_marginal_tax_rate(value):
    payload = _portfolio_payload()
    payload["marginal_tax_rate_pct"] = value
    response = client.post("/assess", json={"portfolio": payload, "monthly_surplus": 15_000.0})
    assert response.status_code == 422


def test_assess_rejects_negative_annual_rental_income():
    payload = _portfolio_payload()
    payload["debts"][2]["annual_rental_income"] = -50_000
    response = client.post("/assess", json={"portfolio": payload, "monthly_surplus": 15_000.0})
    assert response.status_code == 422


@pytest.mark.parametrize("value", [-1, 101, 500])
def test_assess_rejects_out_of_range_foreclosure_charge(value):
    """NEWLY CONSTRAINED (le=100). A charge is a percentage OF the balance,
    so >100% means the fee exceeds the whole debt -- previously accepted,
    and it would have produced a confident, wildly inflated surcharge
    instead of a validation error."""
    payload = _portfolio_payload()
    payload["debts"][1]["rate_type"] = "fixed"
    payload["debts"][1]["foreclosure_charge_pct"] = value
    response = client.post("/assess", json={"portfolio": payload, "monthly_surplus": 15_000.0})
    assert response.status_code == 422


@pytest.mark.parametrize("value", [-1, -50_000])
def test_assess_rejects_negative_monthly_surplus(value):
    """NEWLY CONSTRAINED (ge=0). Previously returned a confident HTTP 200
    whose plan was silently computed as if the surplus were zero."""
    response = client.post(
        "/assess", json={"portfolio": _portfolio_payload(), "monthly_surplus": value}
    )
    assert response.status_code == 422


def test_assess_accepts_zero_monthly_surplus():
    """The boundary must stay OPEN: paying only minimums is a real plan,
    so ge=0 (not gt=0) is the correct constraint."""
    payload = _portfolio_payload()
    response = client.post("/assess", json={"portfolio": payload, "monthly_surplus": 0})
    assert response.status_code == 200


def test_assess_returns_422_not_500_for_a_portfolio_that_cannot_be_paid_off():
    """A borrower whose minimum payments never outpace their interest is a
    real situation, not a server fault. impact.py raises rather than
    looping forever; the endpoint must translate that into a clear 4xx."""
    payload = {
        "borrower_id": "underwater",
        "tax_regime": "old",
        "marginal_tax_rate_pct": 30.0,
        "debts": [
            {
                "debt_id": "pl1", "debt_type": "personal_loan", "outstanding_balance": 1_000_000,
                "stated_apr_pct": 24.0, "remaining_tenure_months": 24, "minimum_payment": 100,
                "rate_type": "floating",
            }
        ],
    }
    response = client.post("/assess", json={"portfolio": payload, "monthly_surplus": 0})
    assert response.status_code == 422
    assert "cannot be paid off" in response.json()["detail"]
