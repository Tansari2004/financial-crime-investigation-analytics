"""Export a bounded, published analytics snapshot for the local preview."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .promote import DEFAULT_DSN


def export_dashboard(dsn: str, output: Path) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        publication = conn.execute(
            "SELECT last_publication_id, published_at FROM analytics.publication_state "
            "WHERE state_id=1"
        ).fetchone()
        if publication["last_publication_id"] is None:
            raise RuntimeError("no analytics publication exists")
        totals = conn.execute(
            "SELECT COALESCE(sum(transaction_count),0) AS transactions, "
            "COALESCE(sum(risk_alert_count),0) AS risk_alerts "
            "FROM analytics.fact_daily_transaction"
        ).fetchone()
        daily = conn.execute(
            "SELECT event_date, from_bank_code, payment_currency, payment_format, "
            "transaction_count, paid_amount, labelled_laundering_count, "
            "risk_alert_count FROM analytics.v_daily_metrics "
            "ORDER BY event_date DESC, from_bank_code, payment_currency LIMIT 5000"
        ).fetchall()
        alerts = conn.execute(
            "SELECT transaction_key, event_time, from_bank_code, from_account_code, "
            "to_bank_code, to_account_code, amount_paid, payment_currency, "
            "payment_format, risk_score, high_amount_for_currency_day, "
            "high_hourly_velocity, repeated_counterparty "
            "FROM analytics.v_risk_alert ORDER BY risk_score DESC, event_time DESC "
            "LIMIT 200"
        ).fetchall()
        quality = conn.execute(
            "SELECT COALESCE(sum(manifest_total),0) AS source_rows, "
            "COALESCE(sum(manifest_accepted),0) AS accepted_rows, "
            "COALESCE(sum(manifest_rejected),0) AS rejected_rows, "
            "COALESCE(sum(manifest_duplicate_candidates),0) AS duplicate_candidates, "
            "count(*) FILTER (WHERE NOT is_balanced) AS imbalanced_files "
            "FROM analytics.file_row_reconciliation"
        ).fetchone()
        deltas = conn.execute(
            "SELECT count(*) AS imbalanced_currency_groups "
            "FROM analytics.file_amount_reconciliation "
            "WHERE raw_staging_delta<>0 OR effective_core_delta<>0"
        ).fetchone()
    document = {
        "kind": "pipeline_export", "publication_id": publication["last_publication_id"],
        "published_at": publication["published_at"].isoformat(),
        "totals": {key: int(value) for key, value in totals.items()},
        "limits": {"daily_rows": 5000, "risk_alerts": 200},
        "daily": [{k: (v.isoformat() if hasattr(v, "isoformat") else
                        str(v) if k == "paid_amount" else v)
                   for k, v in row.items()} for row in daily],
        "alerts": [{k: (v.isoformat() if hasattr(v, "isoformat") else
                         str(v) if k == "amount_paid" else v)
                    for k, v in row.items()} for row in alerts],
        "quality": {**quality, **deltas},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")
    return {"output": str(output), "daily_rows": len(daily), "alerts": len(alerts),
            "publication_id": publication["last_publication_id"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export published dashboard preview")
    parser.add_argument("--dsn", default=os.environ.get("BANKING_DATABASE_URL", DEFAULT_DSN))
    parser.add_argument("--output", type=Path,
                        default=Path("pipeline/dashboard/data.json"))
    args = parser.parse_args()
    print(json.dumps(export_dashboard(args.dsn, args.output)))


if __name__ == "__main__":
    main()
