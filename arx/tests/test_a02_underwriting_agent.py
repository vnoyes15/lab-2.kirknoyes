import pytest

from arx.agents.a02_underwriting_agent import A02ValidationError, run_a02
from arx.agents.loan_math import compute_annual_debt_service
from arx.tests.fakes import FakeModelClient

PURCHASE_PRICE = 5_000_000
LOAN_AMOUNT = 3_750_000
LTV = 0.75
INTEREST_RATE = 0.065
AMORTIZATION_YEARS = 30

NOI = 300_000
ANNUAL_DEBT_SERVICE = compute_annual_debt_service(LOAN_AMOUNT, INTEREST_RATE, AMORTIZATION_YEARS)
DSCR = NOI / ANNUAL_DEBT_SERVICE
COC = (NOI - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV))


def _consistent_model_response(**overrides) -> dict:
    scenario = lambda cap_rate: {"cap_rate": cap_rate, "dscr": DSCR, "coc": COC}
    base = {
        "gross_rent": 500_000,
        "vacancy_rate": 0.07,
        "vacancy_amount": 35_000,
        "operating_expenses": {
            "management": 40_000, "maintenance": 25_000, "capex_reserves": 25_000,
            "insurance": 25_000, "taxes": 40_000, "other": 10_000,
        },
        "noi": NOI,
        "cap_rate": NOI / PURCHASE_PRICE,
        "dscr": DSCR,
        "cash_on_cash": COC,
        "sensitivity_table": {
            "rent_-10pct": scenario(0.052), "rent_-5pct": scenario(0.056), "base": scenario(0.060),
            "rent_+5pct": scenario(0.064), "rent_+10pct": scenario(0.068),
        },
        "load_bearing_assumptions": [
            {"assumption": "vacancy rate", "why_it_matters": "Directly scales NOI."},
            {"assumption": "exit cap rate", "why_it_matters": "Drives eventual disposition value."},
            {"assumption": "interest rate", "why_it_matters": "Sets debt service and DSCR headroom."},
        ],
        "assumption_sources": {"gross_rent": "user_provided", "vacancy_rate": "system_default"},
        "confidence_score": "high",
        "no_comp_disclaimer": "No comparable sales data was available for this submarket.",
    }
    base.update(overrides)
    return base


def _run(model_response, **overrides):
    fake = FakeModelClient(model_response, input_tokens=800, output_tokens=600)
    kwargs = dict(
        gross_rent_hint=500_000, purchase_price=PURCHASE_PRICE, asset_type="multifamily",
        submarket="Tacoma, WA", uw_defaults={"vacancy": 0.07}, loan_amount=LOAN_AMOUNT,
        ltv=LTV, interest_rate=INTEREST_RATE, amortization_years=AMORTIZATION_YEARS,
        comps=None, model_client=fake,
    )
    kwargs.update(overrides)
    return run_a02(**kwargs), fake


def test_run_a02_consistent_output_passes_validation():
    result, fake = _run(_consistent_model_response())
    assert result.validation.passed
    assert result.output.dscr_hard_fail is False
    # These loan terms (75% LTV, 6.5%/30yr) against a 6% cap rate deal genuinely
    # produce a DSCR of ~1.05 — correctly below the 1.25 warning threshold, not a
    # test bug. A tighter-leverage fixture would be needed to exercise dscr_warning=False.
    assert result.output.dscr_warning is True
    assert result.output.annual_debt_service == pytest.approx(ANNUAL_DEBT_SERVICE)
    assert len(fake.calls) == 1


def test_run_a02_healthy_dscr_no_warning():
    # Lower leverage (50% LTV) against the same NOI comfortably clears 1.25.
    lower_loan = PURCHASE_PRICE * 0.50
    ads = compute_annual_debt_service(lower_loan, INTEREST_RATE, AMORTIZATION_YEARS)
    dscr = NOI / ads
    coc = (NOI - ads) / (PURCHASE_PRICE * (1 - 0.50))
    response = _consistent_model_response(dscr=dscr, cash_on_cash=coc)
    for s in response["sensitivity_table"].values():
        s["dscr"] = dscr
        s["coc"] = coc

    result, _ = _run(response, loan_amount=lower_loan, ltv=0.50)
    assert result.validation.passed
    assert result.output.dscr_hard_fail is False
    assert result.output.dscr_warning is False


def test_run_a02_annual_debt_service_is_python_computed_not_model_supplied():
    # Even if the model tried to smuggle a different debt service in, the agent never
    # reads one from the model at all — it's computed before the model is even called
    # and simply overwritten into the merged output (Section 87: "Not model-estimated").
    response = _consistent_model_response()
    response["annual_debt_service"] = 1.0  # would be nonsense if it were ever used
    result, _ = _run(response)
    assert result.output.annual_debt_service == pytest.approx(ANNUAL_DEBT_SERVICE)


def test_run_a02_dscr_hard_fail_computed_from_dscr():
    low_dscr = 0.9
    response = _consistent_model_response(
        dscr=low_dscr,
        cash_on_cash=(NOI - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV)),
    )
    # Recompute NOI/debt-service-derived dscr consistently: force noi down so dscr matches.
    forced_noi = low_dscr * ANNUAL_DEBT_SERVICE
    response["noi"] = forced_noi
    response["cap_rate"] = forced_noi / PURCHASE_PRICE
    response["cash_on_cash"] = (forced_noi - ANNUAL_DEBT_SERVICE) / (PURCHASE_PRICE * (1 - LTV))
    for s in response["sensitivity_table"].values():
        s["dscr"] = low_dscr
    # NOI construction must still hold (MV4): gross_rent*(1-vacancy) - opex = forced_noi
    response["operating_expenses"]["other"] += (NOI - forced_noi)

    result, _ = _run(response)
    assert result.output.dscr_hard_fail is True
    assert result.output.dscr_warning is True


def test_run_a02_rejects_inconsistent_cap_rate():
    bad_response = _consistent_model_response(cap_rate=0.5)  # wildly inconsistent with noi/price
    with pytest.raises(A02ValidationError) as excinfo:
        _run(bad_response)
    assert excinfo.value.failed_checks is not None
    failed_ids = {c["check_id"] for c in excinfo.value.failed_checks["checks"] if not c["passed"]}
    assert "MV1" in failed_ids


def test_run_a02_rejects_schema_violation():
    bad_response = _consistent_model_response()
    bad_response["load_bearing_assumptions"] = bad_response["load_bearing_assumptions"][:1]  # only 1, needs 3
    with pytest.raises(A02ValidationError, match="schema validation"):
        _run(bad_response)


def test_run_a02_sends_uw_defaults_and_loan_terms_to_model():
    _, fake = _run(_consistent_model_response())
    sent = fake.calls[0]["user_message"]
    assert "0.065" in sent  # interest rate
    assert "vacancy" in sent.lower()
