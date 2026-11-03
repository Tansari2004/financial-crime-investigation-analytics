"""Run the real pipeline's replay, correction, and publication rollback demo.

Only a newly created, randomly named database is modified or dropped. The
supplied connection is used to create that database, never to bootstrap it.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from banking_pipeline.analytics import publish
from banking_pipeline.bootstrap import bootstrap
from banking_pipeline.contract import HEADERS
from banking_pipeline.corrections import CORRECTION_HEADER, ingest_corrections
from banking_pipeline.ingest import ingest_file
from banking_pipeline.promote import promote
from banking_pipeline.health import health_html, read_health


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def write_csv(path: Path, header, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def payment(amount: str, sender: str) -> list[str]:
    return ["2026/01/02 09:00", "DEMO01", sender, "DEMO02", "recipient",
            amount, "US Dollar", amount, "US Dollar", "Wire", "0"]


def catch_up(dsn: str) -> None:
    for _ in range(20):
        if promote(dsn)["status"] == "skipped":
            return
    raise RuntimeError("Demo promotion did not finish within 20 batches")


def published_snapshot(dsn: str) -> dict:
    """Capture every published row, not just counts or a limited dashboard."""
    tables = {
        "publication_state": "state_id",
        "publication_run": "publication_id",
        "fact_daily_transaction": "event_date, from_bank_key, payment_currency, payment_format",
        "fact_risk_signal": "transaction_key",
        "file_row_reconciliation": "file_id",
        "file_amount_reconciliation": "file_id, payment_currency",
    }
    with psycopg.connect(dsn) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return {
            table: [row[0] for row in conn.execute(
                sql.SQL("SELECT to_jsonb(t) FROM analytics.{} t ORDER BY " + order)
                .format(sql.Identifier(table))
            ).fetchall()]
            for table, order in tables.items()
        }


def summary(dsn: str) -> dict:
    with psycopg.connect(dsn) as conn:
        raw, accepted, duplicates = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE validation_status='accepted'), "
            "count(*) FILTER (WHERE validation_status='duplicate_candidate') "
            "FROM raw.transaction_record"
        ).fetchone()
        count, amount = conn.execute(
            "SELECT COALESCE(sum(transaction_count),0), COALESCE(sum(paid_amount),0) "
            "FROM analytics.fact_daily_transaction WHERE payment_currency='US Dollar'"
        ).fetchone()
        publication = conn.execute(
            "SELECT last_publication_id FROM analytics.publication_state WHERE state_id=1"
        ).fetchone()[0]
    return {"source_rows": raw, "accepted_rows": accepted,
            "duplicate_candidates": duplicates, "published_rows": int(count),
            "published_usd": str(amount), "publication_id": publication}


def run_demo(dsn: str, output: Path) -> dict:
    bootstrap(dsn)
    with psycopg.connect(dsn) as conn:
        server_version = conn.execute("SHOW server_version").fetchone()[0]
    inputs = output / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    steps = []

    def record(name: str, **details) -> None:
        with psycopg.connect(dsn) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            health = read_health(conn)
        expected = "PUBLICATION FAILED" if name == "4_blocked_publication" else "PUBLISHED"
        require(health["status"] == expected, "Operational status differs at " + name)
        (output / f"{name}_health.json").write_text(json.dumps(health, indent=2) + "\n")
        (output / f"{name}_health.html").write_text(health_html(
            health, scope="Actual execution of the fabricated recovery fixture in a temporary database; not the full IBM run."))
        entry = {"step": name, **details, "health_status": health["status"]}
        steps.append(entry)
        print(json.dumps(entry, sort_keys=True), flush=True)

    first = payment("10.00", "sender-a")
    source = inputs / "sample_Trans.csv"
    write_csv(source, HEADERS, [first, payment("20.00", "sender-b"),
                               payment("30.00", "sender-c"), first])
    loaded = ingest_file(source, dsn)
    catch_up(dsn)
    publish(dsn)
    initial = summary(dsn)
    require((initial["source_rows"], initial["published_rows"],
             initial["duplicate_candidates"]) == (4, 3, 1), "Initial counts differ")
    require(Decimal(initial["published_usd"]) == 60, "Initial total differs")
    with psycopg.connect(dsn) as conn:
        quarantined = conn.execute("SELECT count(*) FROM quarantine.rejected_record").fetchone()[0]
    require(quarantined == 1, "Duplicate candidate was not retained in quarantine")
    record("1_load", **initial, quarantined_rows=quarantined)

    before_replay = published_snapshot(dsn)
    replay = ingest_file(source, dsn)
    catch_up(dsn)
    replay_publication = publish(dsn)
    require(replay["status"] == replay_publication["status"] == "skipped", "Replay was not skipped")
    require(summary(dsn) == initial, "Replay changed counts or totals")
    require(published_snapshot(dsn) == before_replay, "Replay changed published data")
    record("2_replay", file_status=replay["status"], publication_status=replay_publication["status"],
           counts_and_published_rows_unchanged=True)

    with psycopg.connect(dsn) as conn:
        target = conn.execute(
            "SELECT raw_record_id FROM raw.transaction_record WHERE file_id=%s AND source_row_number=2",
            (loaded["file_id"],),
        ).fetchone()[0]
    corrections = inputs / "sample_corrections.csv"
    write_csv(corrections, CORRECTION_HEADER, [[target, *payment("15.00", "sender-a")]])
    ingest_corrections(corrections, dsn)
    catch_up(dsn)
    publish(dsn)
    with psycopg.connect(dsn) as conn:
        original = conn.execute("SELECT payload->>'amount_paid' FROM raw.transaction_record WHERE raw_record_id=%s", (target,)).fetchone()[0]
        correction = conn.execute("SELECT payload->>'amount_paid' FROM raw.transaction_correction WHERE target_raw_record_id=%s", (target,)).fetchone()[0]
        current, correction_id = conn.execute("SELECT amount_paid, current_correction_id FROM core.fact_transaction WHERE source_raw_record_id=%s", (target,)).fetchone()
    require((original, correction, current) == ("10.00", "15.00", Decimal("15")), "Correction history differs")
    corrected = summary(dsn)
    require(corrected["published_rows"] == 3 and Decimal(corrected["published_usd"]) == 65, "Correction publication differs")
    record("3_correction", original_paid=original, correction_paid=correction,
           current_paid=str(current), correction_id=correction_id, **corrected)

    # Controlled faulty transformation, exclusively inside this disposable DB.
    before_failure = published_snapshot(dsn)
    pending = inputs / "next_Trans.csv"
    write_csv(pending, HEADERS, [payment("40.00", "sender-d")])
    next_file = ingest_file(pending, dsn)
    catch_up(dsn)
    with psycopg.connect(dsn) as conn:
        changed = conn.execute("UPDATE core.fact_transaction SET amount_paid=999.00 WHERE source_file_id=%s RETURNING source_raw_record_id", (next_file["file_id"],)).fetchall()
    require(len(changed) == 1, "Fault injection did not target exactly one demo row")
    try:
        publish(dsn)
    except psycopg.Error as exc:
        failure_message = exc.diag.message_primary or str(exc)
        require("amount reconciliation failed" in failure_message, "Unexpected failure: " + failure_message)
    else:
        raise RuntimeError("Publication unexpectedly accepted a mismatched amount")
    after_failure = published_snapshot(dsn)
    require(after_failure == before_failure, "Failed publication altered published tables")
    with psycopg.connect(dsn) as conn:
        failures = conn.execute("SELECT count(*) FROM ops.analytics_failure").fetchone()[0]
    require(failures == 1, "Expected one recorded publication failure")
    record("4_blocked_publication", error=failure_message, injected_paid="999.00",
           expected_paid="40.00", all_published_rows_unchanged=True,
           failure_log_rows=failures, **summary(dsn))
    for name, snapshot in (("before_failed_publication", before_failure),
                           ("after_failed_publication", after_failure)):
        (output / f"{name}.json").write_text(json.dumps(snapshot, indent=2) + "\n")

    with psycopg.connect(dsn) as conn:
        conn.execute("UPDATE core.fact_transaction f SET amount_paid=s.amount_paid FROM staging.transaction_typed s WHERE f.source_raw_record_id=s.raw_record_id AND f.source_file_id=%s", (next_file["file_id"],))
    recovered = publish(dsn)
    final = summary(dsn)
    require(recovered["status"] == "published" and final["published_rows"] == 4, "Recovery failed")
    require(Decimal(final["published_usd"]) == 105, "Recovered total differs")
    with psycopg.connect(dsn) as conn:
        policy = conn.execute("SELECT max_rejected_fraction FROM ops.quality_policy WHERE policy_name='transaction_files'").fetchone()[0]
        imbalances = conn.execute("SELECT count(*) FROM analytics.file_amount_reconciliation WHERE raw_staging_delta<>0 OR effective_core_delta<>0").fetchone()[0]
    require(policy == Decimal("0.05") and imbalances == 0, "Quality policy changed or totals do not reconcile")
    record("5_recovered", quality_policy_unchanged=True, imbalanced_currency_groups=imbalances, **final)
    return {"status": "passed", "steps": steps,
            "environment": {"postgresql": server_version, "python": sys.version.split()[0]},
            "scope": "Fabricated four-row initial fixture and one additional payment; not the full IBM dataset.",
            "failure_method": "Intentional core amount mismatch in a new disposable database; no quality threshold relaxed."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-dsn", default=os.environ.get("BANKING_DEMO_ADMIN_DSN", "postgresql:///postgres"),
                        help="PostgreSQL connection with CREATEDB permission; its existing data is never modified")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/recovery-demo"))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    report_path.write_text(json.dumps({"status": "running"}) + "\n")
    database = "banking_demo_" + uuid4().hex
    options = conninfo_to_dict(args.admin_dsn)
    options["dbname"] = database
    dsn = make_conninfo(**options)
    created = False
    try:
        with psycopg.connect(args.admin_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            created = True
        report = run_demo(dsn, output)
        report["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["database"] = database
    except BaseException:
        # Never leave a previous run's success report looking current.
        report_path.write_text(json.dumps({"status": "failed"}) + "\n")
        raise
    finally:
        if created:
            with psycopg.connect(args.admin_dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
    report["temporary_database_removed"] = True
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    transcript = "\n".join(json.dumps(step, sort_keys=True) for step in report["steps"])
    (output / "transcript.txt").write_text(transcript + "\nPASS: all five steps; temporary database removed.\n", encoding="utf-8")
    print("PASS: all five steps; temporary database removed.")
    print(f"Evidence: {output}")


if __name__ == "__main__":
    main()
