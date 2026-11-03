import pandas as pd

from financial_crime.explain_cases import factor_text, display_amount


def test_explanations_do_not_hide_subcent_amounts():
    row = pd.Series({"amount_paid": .025852, "prior_average_amount": .00123456789,
                     "payment_currency": "Bitcoin"})
    assert factor_text("log_amount_paid", row) == "Payment amount: 0.025852 Bitcoin"
    assert factor_text("log_prior_average_amount", row) == "Earlier average payment: 0.00123456789 Bitcoin"
    assert display_amount(1200.0) == "1,200"
    assert display_amount(1234.56) == "1,234.56"
