"""Read-only operational summary from existing pipeline records."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path

from .promote import DEFAULT_DSN


def read_health(conn) -> dict:
    """Use an existing snapshot transaction; never infer end-to-end timings."""
    state = conn.execute(
        "SELECT last_publication_id, published_at, last_promotion_run_id, last_file_id "
        "FROM analytics.publication_state WHERE state_id=1"
    ).fetchone()
    publication_id, published_at, published_run, published_file = state
    latest = conn.execute(
        "SELECT file_id, status, started_at, completed_at FROM ops.file_manifest "
        "ORDER BY started_at DESC, file_id DESC LIMIT 1"
    ).fetchone()
    counts = conn.execute(
        "SELECT count(*), COALESCE(sum(total_rows),0), COALESCE(sum(accepted_rows),0), "
        "COALESCE(sum(rejected_rows),0), COALESCE(sum(duplicate_candidates),0), "
        "count(*) FILTER (WHERE status='failed'), count(*) FILTER (WHERE status='started') "
        "FROM ops.file_manifest"
    ).fetchone()
    correction_files = conn.execute(
        "SELECT count(*) FILTER (WHERE status='failed'), count(*) FILTER (WHERE status='started') "
        "FROM ops.correction_file_manifest"
    ).fetchone()
    promotion = conn.execute(
        "SELECT last_raw_record_id, last_correction_id FROM ops.pipeline_state "
        "WHERE pipeline_name='transaction_promotion'"
    ).fetchone()
    pending = conn.execute(
        "SELECT (SELECT count(*) FROM raw.transaction_record WHERE validation_status='accepted' "
        "AND raw_record_id>%s), (SELECT count(*) FROM raw.transaction_correction WHERE correction_id>%s)",
        promotion,
    ).fetchone()
    run_id, last_promotion = conn.execute(
        "SELECT COALESCE(max(promotion_run_id),0), max(completed_at) "
        "FROM ops.promotion_run WHERE status='completed'"
    ).fetchone()
    last_file = conn.execute("SELECT max(completed_at) FROM ops.file_manifest WHERE status='completed'").fetchone()[0]
    last_analytics_failure = conn.execute("SELECT max(occurred_at) FROM ops.analytics_failure").fetchone()[0]
    last_promotion_failure = conn.execute("SELECT max(occurred_at) FROM ops.promotion_failure").fetchone()[0]
    published_rows = conn.execute("SELECT COALESCE(sum(transaction_count),0) FROM analytics.fact_daily_transaction").fetchone()[0]
    now = datetime.now(timezone.utc)

    def after(failure, success):
        return failure is not None and (success is None or failure > success)

    if counts[5] or correction_files[0]:
        status = "FAILED FILES"
    elif counts[6] or correction_files[1]:
        status = "LOADING"
    elif after(last_analytics_failure, published_at):
        status = "PUBLICATION FAILED"
    elif after(last_promotion_failure, max(filter(None, [last_promotion, published_at]), default=None)):
        status = "PROMOTION FAILED"
    elif any(pending):
        status = "AWAITING PROMOTION"
    elif run_id > published_run or after(last_file, published_at):
        status = "AWAITING PUBLICATION"
    elif publication_id is None:
        status = "NO PUBLICATION" if counts[0] else "NO DATA"
    else:
        status = "PUBLISHED"

    def timestamp(value):
        return value.astimezone(timezone.utc).isoformat() if value else None

    duration = None
    if latest and latest[1] == "completed" and latest[3] is not None:
        duration = round((latest[3] - latest[2]).total_seconds(), 6)
    return {
        "status": status, "captured_at_utc": timestamp(now),
        "latest_file_id": latest[0] if latest else None,
        "latest_file_status": latest[1] if latest else None,
        "latest_file_started_at_utc": timestamp(latest[2]) if latest else None,
        "latest_file_completed_at_utc": timestamp(latest[3]) if latest else None,
        "latest_file_ingestion_seconds": duration,
        "duration_scope": "Latest completed file-ingestion attempt only; not promotion, publication, Power BI refresh or end-to-end runtime.",
        "source_rows": int(counts[1]), "accepted_rows": int(counts[2]),
        "rejected_rows": int(counts[3]), "duplicate_candidates": int(counts[4]),
        "counts_scope": "Committed source-file manifests, including files not yet published.",
        "published_rows": int(published_rows), "publication_id": publication_id,
        "latest_successful_publication_utc": timestamp(published_at),
        "publication_age_seconds_at_capture": round((now - published_at).total_seconds(), 3) if published_at else None,
        "pending_source_rows": pending[0], "pending_corrections": pending[1],
        "last_publication_failure_utc": timestamp(last_analytics_failure),
        "failed_source_files": counts[5], "failed_correction_files": correction_files[0],
    }


def health_html(health: dict, *, scope: str) -> str:
    rows = [
        ("Pipeline status", health["status"], "Observed at capture; this saved page does not poll the database."),
        ("Latest file ingestion", health["latest_file_status"], f"File {health['latest_file_id']}"),
        ("File-ingestion duration (seconds)", health["latest_file_ingestion_seconds"], health["duration_scope"]),
        ("Source rows", health["source_rows"], health["counts_scope"]),
        ("Accepted source rows", health["accepted_rows"], "Acceptance is separate from publication."),
        ("Rejected source rows", health["rejected_rows"], "Invalid input; excluded and retained in quarantine."),
        ("Duplicate candidates", health["duplicate_candidates"], "Separate from invalid rejects; retained for inspection."),
        ("Published rows", health["published_rows"], "Last successful daily-mart publication."),
        ("Last successful publication (UTC)", health["latest_successful_publication_utc"], f"Publication {health['publication_id']}"),
        ("Publication age at capture (seconds)", health["publication_age_seconds_at_capture"], "Age alone is not labelled stale without an agreed schedule."),
        ("Pending source rows / corrections", f"{health['pending_source_rows']} / {health['pending_corrections']}", "Awaiting promotion; promoted rows may still await publication."),
        ("Last publication failure (UTC)", health["last_publication_failure_utc"], "Historical failure remains visible after recovery."),
    ]
    table = "".join(f"<tr><th scope='row'>{escape(label)}</th><td>{escape(str(value)) if value is not None else 'Not available'}</td><td>{escape(note)}</td></tr>" for label, value, note in rows)
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Banking pipeline health</title><style>body{{font:16px/1.5 system-ui,sans-serif;color:#172c47;background:#f5f8fc;margin:0;padding:32px}}main{{max-width:1100px;margin:auto}}h1{{margin-bottom:8px}}.scope{{border-left:4px solid #2476bd;padding:10px 16px;background:#e9f1fb}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;background:white;margin-top:24px}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #dae3ee;padding:13px}}thead{{background:#173d65;color:white}}tbody th{{width:28%}}td:last-child{{color:#526276;font-size:14px}}footer{{margin-top:18px;color:#526276}}@media(max-width:600px){{body{{padding:16px}}th,td{{padding:10px}}}}</style>
<main><p>Banking Transaction Data Platform</p><h1>Pipeline health</h1><p class="scope">{escape(scope)}</p><p>Captured {escape(health['captured_at_utc'])}. Read-only summary of existing operational records.</p><div class="scroll"><table><thead><tr><th>Measure</th><th>Observed value</th><th>Meaning / scope</th></tr></thead><tbody>{table}</tbody></table></div><footer>Source acceptance and published reporting are separate boundaries. No account identifiers, source paths or credentials are included.</footer></main></html>"""


def main():
    import psycopg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("BANKING_DATABASE_URL", DEFAULT_DSN))
    parser.add_argument("--output", type=Path, default=Path("data/processed/pipeline-health.json"))
    parser.add_argument("--html", type=Path, default=Path("data/processed/pipeline-health.html"))
    args = parser.parse_args()
    with psycopg.connect(args.dsn) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        result = read_health(conn)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    args.html.write_text(health_html(result, scope="Database snapshot captured by the read-only exporter; not a live dashboard."))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
