import pytest

from arx.agents.loan_math import compute_annual_debt_service


def test_annual_debt_service_fully_amortizes_to_zero():
    """Self-consistency check independent of any memorized reference figure: the
    computed monthly payment, applied every month at the same monthly rate, must
    fully retire the loan balance by the end of the amortization term."""
    loan_amount, interest_rate, amortization_years = 3_750_000, 0.065, 30
    annual_debt_service = compute_annual_debt_service(loan_amount, interest_rate, amortization_years)
    monthly_payment = annual_debt_service / 12
    monthly_rate = interest_rate / 12

    balance = loan_amount
    for _ in range(amortization_years * 12):
        interest = balance * monthly_rate
        principal = monthly_payment - interest
        balance -= principal

    assert balance == pytest.approx(0.0, abs=0.01)


def test_annual_debt_service_zero_rate_is_straight_line():
    annual_debt_service = compute_annual_debt_service(1_200_000, 0.0, 30)
    assert annual_debt_service == pytest.approx(1_200_000 / 30)


@pytest.mark.parametrize("bad_kwargs", [
    {"loan_amount": 0, "interest_rate": 0.06, "amortization_years": 30},
    {"loan_amount": 100, "interest_rate": 0.06, "amortization_years": 0},
])
def test_annual_debt_service_rejects_invalid_inputs(bad_kwargs):
    with pytest.raises(ValueError):
        compute_annual_debt_service(**bad_kwargs)
