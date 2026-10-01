"""Versioned source contract for IBM AML HI-Small transaction CSV files."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

HEADERS = (
    "Timestamp", "From Bank", "Account", "To Bank", "Account",
    "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency",
    "Payment Format", "Is Laundering",
)
KEYS = (
    "timestamp", "from_bank", "from_account", "to_bank", "to_account",
    "amount_received", "receiving_currency", "amount_paid", "payment_currency",
    "payment_format", "is_laundering",
)
SCHEMA_VERSION = "ibm-aml-hi-small-v2"


def amount_scale(currency: str) -> int:
    """The IBM export uses six decimal places for Bitcoin, two otherwise."""
    return 6 if currency.strip() == "Bitcoin" else 2


def validate_row(values: list[str]) -> list[str]:
    if len(values) != len(HEADERS):
        return ["wrong_column_count"]
    errors: list[str] = []
    try:
        datetime.strptime(values[0].strip(), "%Y/%m/%d %H:%M")
    except ValueError:
        try:
            datetime.strptime(values[0].strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            errors.append("invalid_timestamp")
    for index, name in ((1, "from_bank"), (2, "from_account"), (3, "to_bank"),
                        (4, "to_account"), (6, "receiving_currency"),
                        (8, "payment_currency"), (9, "payment_format")):
        if not values[index].strip():
            errors.append(f"missing_{name}")
    for index, currency_index, name in (
        (5, 6, "amount_received"), (7, 8, "amount_paid")
    ):
        try:
            amount = Decimal(values[index].strip())
            if (not amount.is_finite() or amount < 0 or
                    amount.as_tuple().exponent < -amount_scale(values[currency_index])
                    or amount >= Decimal("1e18")):
                errors.append(f"invalid_{name}")
        except InvalidOperation:
            errors.append(f"invalid_{name}")
    if values[10].strip() not in {"0", "1"}:
        errors.append("invalid_laundering_label")
    return errors


def payload_for(values: list[str]) -> dict[str, str]:
    return {key: value.strip() for key, value in zip(KEYS, values)}
