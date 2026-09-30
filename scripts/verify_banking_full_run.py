"""Verify and record evidence for a completed banking pipeline load.

Run this only after ingestion, promotion, and analytics publication. It reads
database aggregates and does not load another copy of the source dataset.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def verify(dsn: str, min_source_rows: int) -> dict:
    if min_source_rows < 1:
        raise ValueError("min_source_rows must be positive")
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        files = conn.execute(
            "SELECT count(*) AS completed_files, "
            "COALESCE(sum(total_rows),0)::bigint AS source_rows, "
            "COALESCE(sum(accepted_rows),0)::bigint AS accepted_rows, "
            "COALESCE(sum(rejected_rows),0)::bigint AS rejected_rows, "
            "COALESCE(sum(duplicate_candidates),0)::bigint AS duplicate_candidates, "
            "COALESCE(max(file_id),0) AS latest_file_id "
            "FROM ops.file_manifest WHERE status='completed'"
        ).fetchone()
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM raw.transaction_record) AS raw_rows, "
            "(SELECT count(*) FROM staging.transaction_typed) AS staged_rows, "
            "(SELECT count(*) FROM core.fact_transaction) AS core_rows, "
            "(SELECT count(*) FROM analytics.fact_risk_signal) AS risk_rows, "
            "(SELECT COALESCE(sum(transaction_count),0)::bigint "
            " FROM analytics.fact_daily_transaction) AS mart_transactions, "
            "(SELECT count(*) FROM analytics.file_row_reconciliation "
            " WHERE NOT is_balanced) AS unbalanced_files, "
            "(SELECT count(*) FROM analytics.file_amount_reconciliation "
            " WHERE raw_staging_delta<>0 OR effective_core_delta<>0) "
            " AS unbalanced_currency_groups, "
            "(SELECT count(*) FROM ops.file_manifest WHERE status<>'completed') "
            " AS incomplete_files, "
            "(SELECT COALESCE(max(promotion_run_id),0) FROM ops.promotion_run "
            " WHERE status='completed') AS latest_promotion_run_id"
        ).fetchone()
        publication = conn.execute(
            "SELECT last_publication_id, last_file_id, last_promotion_run_id, "
            "published_at FROM analytics.publication_state WHERE state_id=1"
        ).fetchone()
        cursor = conn.execute(
            "SELECT last_raw_record_id FROM ops.pipeline_state "
            "WHERE pipeline_name='transaction_promotion'"
        ).fetchone()
        pending = conn.execute(
            "SELECT count(*) AS pending_accepted FROM raw.transaction_record "
            "WHERE validation_status='accepted' AND raw_record_id>%s",
            (cursor["last_raw_record_id"],),
        ).fetchone()

    checks = {
        "minimum_source_rows": files["source_rows"] >= min_source_rows,
        "all_files_completed": counts["incomplete_files"] == 0,
        "manifest_arithmetic": files["source_rows"] == (
            files["accepted_rows"] + files["rejected_rows"]
            + files["duplicate_candidates"]
        ),
        "manifest_to_raw": files["source_rows"] == counts["raw_rows"],
        "accepted_to_staging": files["accepted_rows"] == counts["staged_rows"],
        "staging_to_core": counts["staged_rows"] == counts["core_rows"],
        "core_to_risk": counts["core_rows"] == counts["risk_rows"],
        "core_to_mart": counts["core_rows"] == counts["mart_transactions"],
        "row_reconciliation": counts["unbalanced_files"] == 0,
        "amount_reconciliation": counts["unbalanced_currency_groups"] == 0,
        "no_pending_accepted_rows": pending["pending_accepted"] == 0,
        "publication_caught_up": publication["last_publication_id"] is not None
        and publication["last_file_id"] == files["latest_file_id"]
        and publication["last_promotion_run_id"] == counts["latest_promotion_run_id"],
    }
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "min_source_rows": min_source_rows,
        "files": dict(files),
        "counts": dict(counts),
        "publication": {
            **dict(publication),
            "published_at": publication["published_at"].isoformat()
            if publication["published_at"] else None,
        },
        "pending_accepted_rows": pending["pending_accepted"],
        "checks": checks,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("BANKING_DATABASE_URL"))
    parser.add_argument("--min-source-rows", type=int, default=5_000_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.dsn:
        parser.error("set BANKING_DATABASE_URL or --dsn")
    report = verify(args.dsn, args.min_source_rows)
    document = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    print(document, end="")
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
