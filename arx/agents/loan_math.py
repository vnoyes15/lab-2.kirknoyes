"""Deterministic loan math — Section 87: "annual_debt_service R float — Python-
calculated from loan_amount, interest_rate, amortization_years. Not model-estimated."

Standard monthly-amortizing mortgage-style payment, annualized. Pure function, no AI,
same contract as arx/validation/*.
"""


def compute_annual_debt_service(loan_amount: float, interest_rate: float, amortization_years: int) -> float:
    if loan_amount <= 0:
        raise ValueError("loan_amount must be > 0")
    if amortization_years <= 0:
        raise ValueError("amortization_years must be > 0")

    n_payments = amortization_years * 12
    if interest_rate == 0:
        monthly_payment = loan_amount / n_payments
    else:
        monthly_rate = interest_rate / 12
        monthly_payment = loan_amount * monthly_rate / (1 - (1 + monthly_rate) ** -n_payments)

    return monthly_payment * 12
