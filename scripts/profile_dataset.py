#!/usr/bin/env python3
"""Profile a CSV transaction dataset without assuming IBM AML column names.

The script writes a Markdown report that is intended to be the factual input for
the Phase 1 data model and Phase 2 SQL design.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

LABEL_CANDIDATES = {
    "is_laundering",
    "laundering",
    "label",
    "target",
    "is_suspicious",
    "suspicious",
}
AMOUNT_CANDIDATES = {"amount", "transaction_amount", "amount_received", "value", "payment_amount"}


def find_column(columns: list[str], candidates: set[str]) -> str | None:
    """Return a case-insensitive exact candidate match, if present."""
    normalized = {re.sub(r"[^a-z0-9]+", "_", column.strip().lower()).strip("_"): column for column in columns}
    return next((normalized[name] for name in candidates if name in normalized), None)


def render_table(frame: "pd.DataFrame") -> str:
    return frame.to_markdown(index=False) if not frame.empty else "_None_"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Path to a transaction CSV file")
    parser.add_argument("--sample-rows", type=int, default=None, help="Read only the first N rows")
    parser.add_argument(
        "--report-path", type=Path, default=Path("reports/dataset_profile.md"), help="Markdown output path"
    )
    args = parser.parse_args()

    if not args.csv_path.is_file():
        raise SystemExit(f"CSV not found: {args.csv_path}")
    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be positive")

    import pandas as pd

    transactions = pd.read_csv(args.csv_path, nrows=args.sample_rows, low_memory=False)
    rows, columns = transactions.shape
    overview = pd.DataFrame(
        {
            "column": transactions.columns,
            "dtype": [str(dtype) for dtype in transactions.dtypes],
            "missing_values": transactions.isna().sum().values,
            "missing_pct": (transactions.isna().mean() * 100).round(2).values,
            "unique_values": transactions.nunique(dropna=True).values,
        }
    )

    label_column = find_column(list(transactions.columns), LABEL_CANDIDATES)
    amount_column = find_column(list(transactions.columns), AMOUNT_CANDIDATES)
    sections = [
        "# Dataset Profile",
        "",
        f"- Source file: `{args.csv_path}`",
        f"- Rows profiled: {rows:,}" + (" (sample)" if args.sample_rows else ""),
        f"- Columns: {columns}",
        "",
        "## Schema and data quality",
        "",
        render_table(overview),
    ]

    sections.extend(["", "## Target distribution"])
    if label_column:
        distribution = transactions[label_column].value_counts(dropna=False).rename_axis(label_column).reset_index(name="count")
        distribution["percent"] = (distribution["count"] / rows * 100).round(4)
        sections.extend(["", f"Detected label column: `{label_column}`", "", render_table(distribution)])
    else:
        sections.extend(["", "No label was inferred. Confirm the label name from the schema before modelling."])

    sections.extend(["", "## Transaction amount statistics"])
    if amount_column:
        amount = pd.to_numeric(transactions[amount_column], errors="coerce")
        stats = amount.describe(percentiles=[0.01, 0.5, 0.95, 0.99]).rename_axis("statistic").reset_index(name="value")
        sections.extend(["", f"Detected amount column: `{amount_column}`", "", render_table(stats)])
    else:
        sections.extend(["", "No standard amount column was inferred. Identify it manually from the schema."])

    sections.extend(
        [
            "",
            "## Interpretation notes",
            "",
            "This report describes the file as read. Inferred label and amount fields are convenience checks, not schema assumptions.",
            "Use the actual column names above to design the PostgreSQL table and later features.",
        ]
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"Wrote {args.report_path}")


if __name__ == "__main__":
    main()
