"""Create the small, browser-ready JSON file from explained test cases."""

from __future__ import annotations

import csv
import json
from pathlib import Path

SOURCE = Path("data/processed/dashboard_cases.csv")
OUTPUT = Path("data/processed/dashboard_cases.json")


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit("Missing explained cases. Run sql/dashboard_export.sql and explain_cases.py first.")

    rows = []
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            rows.append({
                "review_rank": int(record["review_rank"]),
                "transaction_id": int(record["transaction_id"]),
                "review_score": float(record["review_score"]),
                "transaction_time": record["transaction_time"],
                "from_bank": record["from_bank"],
                "from_account": record["from_account"],
                "to_bank": record["to_bank"],
                "to_account": record["to_account"],
                "amount_paid": float(record["amount_paid"]),
                "payment_currency": record["payment_currency"],
                "payment_format": record["payment_format"],
                "prior_transaction_count": int(float(record["prior_transaction_count"])),
                "prior_average_amount": float(record["prior_average_amount"]),
                "amount_spike_rule": record["amount_spike_rule"].lower() == "true",
                "amount_to_earlier_average": float(record["amount_to_earlier_average"])
                if record["amount_to_earlier_average"] else None,
                "model_reasons": [record[f"model_reason_{index}"] for index in (1, 2, 3)
                                  if record[f"model_reason_{index}"]],
                "rule_reason": record["rule_reason"],
            })

    if len(rows) != 10_000 or [row["review_rank"] for row in rows] != list(range(1, 10_001)):
        raise SystemExit("Expected exactly 10,000 consecutively ranked cases")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"source": "synthetic IBM AML later-period test split",
                                  "model_version": "numpy_logistic_v1", "rows": rows},
                                 separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(rows):,} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
