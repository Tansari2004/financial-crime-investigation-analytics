"""End-to-end publication, reconciliation, correction, and rollback tests."""

import csv
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from banking_pipeline.analytics import publish
from banking_pipeline.bootstrap import bootstrap
from banking_pipeline.contract import HEADERS
from banking_pipeline.corrections import CORRECTION_HEADER, ingest_corrections
from banking_pipeline.export_dashboard import export_dashboard
from banking_pipeline.ingest import ingest_file
from banking_pipeline.promote import promote


DSN = os.environ.get("BANKING_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set BANKING_TEST_DATABASE_URL")


def _csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def _catch_up() -> None:
    while promote(DSN)["status"] != "skipped":
        pass


def test_analytics_publication_and_quality_rollback(tmp_path: Path) -> None:
    import psycopg

    bootstrap(DSN)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.quality_policy SET max_rejected_fraction=1 "
            "WHERE policy_name='transaction_files'"
        )
    _catch_up()
    publish(DSN)

    marker = uuid4().hex[:12]
    from_bank = f"F{marker}"
    to_bank = f"T{marker}"
    rows = []
    for n in range(5):
        amount = f"{10 + n}.00"
        rows.append(["2030/01/01 10:00", from_bank, f"A{marker}", to_bank, f"B{marker}",
                     amount, "US Dollar", amount, "US Dollar", "Wire",
                     "1" if n == 0 else "0"])
    source = tmp_path / "analytics_Trans.csv"
    _csv(source, HEADERS, rows)
    loaded = ingest_file(source, DSN)
    assert loaded["accepted_rows"] == 5
    _catch_up()
    first_publication = publish(DSN)
    assert first_publication["status"] == "published"
    assert first_publication["affected_days"] >= 1
    assert publish(DSN)["status"] == "skipped"

    with psycopg.connect(DSN) as conn:
        daily = conn.execute(
            "SELECT transaction_count, paid_amount, labelled_laundering_count, "
            "risk_alert_count FROM analytics.v_daily_metrics "
            "WHERE event_date='2030-01-01' AND from_bank_code=%s "
            "AND payment_currency='US Dollar' AND payment_format='Wire'",
            (from_bank,),
        ).fetchone()
        alert_count = conn.execute(
            "SELECT count(*) FROM analytics.v_risk_alert "
            "WHERE event_date='2030-01-01' AND from_account_code=%s",
            (f"A{marker}",),
        ).fetchone()[0]
        original_id = conn.execute(
            "SELECT raw_record_id FROM raw.transaction_record "
            "WHERE file_id=%s AND source_row_number=2", (loaded["file_id"],),
        ).fetchone()[0]
        second_id = conn.execute(
            "SELECT raw_record_id FROM raw.transaction_record "
            "WHERE file_id=%s AND source_row_number=3", (loaded["file_id"],),
        ).fetchone()[0]
    assert daily == (5, 60, 1, 5)
    assert alert_count == 5
    snapshot_path = tmp_path / "published.json"
    assert export_dashboard(DSN, snapshot_path)["publication_id"] == first_publication["publication_id"]
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["totals"]["transactions"] >= 5

    replacement = rows[0].copy()
    replacement[0] = "2029/12/31 10:00"
    replacement[5] = "99.00"
    replacement[6] = "Euro"
    replacement[7] = "99.00"
    replacement[8] = "Euro"
    corrections = tmp_path / "analytics_corrections.csv"
    _csv(corrections, CORRECTION_HEADER, [[str(original_id), *replacement]])
    ingest_corrections(corrections, DSN)
    _catch_up()
    corrected_publication = publish(DSN)
    assert corrected_publication["affected_days"] >= 2
    with psycopg.connect(DSN) as conn:
        old_day = conn.execute(
            "SELECT transaction_count, paid_amount, risk_alert_count "
            "FROM analytics.v_daily_metrics WHERE event_date='2030-01-01' "
            "AND from_bank_code=%s AND payment_currency='US Dollar'",
            (from_bank,),
        ).fetchone()
        new_day = conn.execute(
            "SELECT transaction_count, paid_amount FROM analytics.v_daily_metrics "
            "WHERE event_date='2029-12-31' AND from_bank_code=%s "
            "AND payment_currency='Euro'",
            (from_bank,),
        ).fetchone()
        amounts = conn.execute(
            "SELECT payment_currency, expected_current_paid, core_paid, "
            "raw_staging_delta, effective_core_delta "
            "FROM analytics.file_amount_reconciliation WHERE file_id=%s "
            "ORDER BY payment_currency", (loaded["file_id"],),
        ).fetchall()
        rows_balanced = conn.execute(
            "SELECT is_balanced FROM analytics.file_row_reconciliation "
            "WHERE file_id=%s", (loaded["file_id"],),
        ).fetchone()[0]
    assert old_day == (4, 50, 0)
    assert new_day == (1, 99)
    assert rows_balanced
    assert amounts == [("Euro", 99, 99, 0, 0), ("US Dollar", 50, 50, 0, 0)]

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.quality_policy SET max_rejected_fraction=0.05 "
            "WHERE policy_name='transaction_files'"
        )
    bad_file = tmp_path / "quality_Trans.csv"
    good = ["2031/01/01 09:00", f"G{marker}", f"C{marker}",
            f"H{marker}", f"D{marker}",
            "1.00", "US Dollar", "1.00", "US Dollar", "Cheque", "0"]
    bad = good.copy()
    bad[0] = "not-a-time"
    _csv(bad_file, HEADERS, [good, bad])
    assert ingest_file(bad_file, DSN)["rejected_rows"] == 1
    unpublished = rows[1].copy()
    unpublished[5] = "888.00"
    unpublished[7] = "888.00"
    unpublished_file = tmp_path / "unpublished_corrections.csv"
    _csv(unpublished_file, CORRECTION_HEADER, [[str(second_id), *unpublished]])
    ingest_corrections(unpublished_file, DSN)
    _catch_up()
    with pytest.raises(psycopg.Error, match="rejected-row fraction"):
        publish(DSN)
    with psycopg.connect(DSN) as conn:
        published_id = conn.execute(
            "SELECT last_publication_id FROM analytics.publication_state WHERE state_id=1"
        ).fetchone()[0]
        premature_rows = conn.execute(
            "SELECT count(*) FROM analytics.v_daily_metrics "
            "WHERE event_date='2031-01-01' AND from_bank_code=%s",
            (f"G{marker}",),
        ).fetchone()[0]
        failure_count = conn.execute(
            "SELECT count(*) FROM ops.analytics_failure"
        ).fetchone()[0]
        published_amount = conn.execute(
            "SELECT amount_paid FROM analytics.fact_risk_signal "
            "WHERE source_raw_record_id=%s", (second_id,),
        ).fetchone()[0]
    assert published_id == corrected_publication["publication_id"]
    assert premature_rows == 0
    assert failure_count >= 1
    assert published_amount == 11

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.quality_policy SET max_rejected_fraction=1 "
            "WHERE policy_name='transaction_files'"
        )
    assert publish(DSN)["status"] == "published"
