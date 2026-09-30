"""Integration coverage for typed promotion, late arrivals, corrections and backfill."""

import csv
import os
from pathlib import Path
from uuid import uuid4

import pytest

from banking_pipeline.contract import HEADERS
from banking_pipeline.corrections import CORRECTION_HEADER, ingest_corrections
from banking_pipeline.ingest import ingest_file
from banking_pipeline.promote import promote


DSN = os.environ.get("BANKING_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set BANKING_TEST_DATABASE_URL")


def _write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def test_incremental_late_correction_and_backfill(tmp_path: Path) -> None:
    import psycopg

    sql_dir = Path(__file__).parents[1] / "pipeline/sql"
    with psycopg.connect(DSN, autocommit=True) as conn:
        for filename in ("001_foundation.sql", "002_model.sql", "003_promotion.sql"):
            conn.execute((sql_dir / filename).read_text())

    # Drain any source rows left by a preceding integration test.
    while promote(DSN, raw_limit=100000)["status"] != "skipped":
        pass

    unique = uuid4().hex[:12]
    first = ["2025/01/03 10:00", "001", f"A{unique}", "002", f"B{unique}",
             "125.50", "US Dollar", "125.50", "US Dollar", "Wire", "0"]
    second = ["2025/01/04 10:00", "001", f"A{unique}", "003", f"C{unique}",
              "200.00", "US Dollar", "200.00", "US Dollar", "Wire", "1"]
    source = tmp_path / "first_Trans.csv"
    _write_csv(source, HEADERS, [first, second])
    source_result = ingest_file(source, DSN)
    assert source_result["accepted_rows"] == 2

    with psycopg.connect(DSN) as conn:
        second_raw_id = conn.execute(
            "SELECT raw_record_id FROM raw.transaction_record "
            "WHERE file_id=%s AND source_row_number=3", (source_result["file_id"],),
        ).fetchone()[0]
    pending_replacement = second.copy()
    pending_replacement[5] = "250.00"
    pending_replacement[7] = "250.00"
    pending_file = tmp_path / "pending_corrections.csv"
    _write_csv(pending_file, CORRECTION_HEADER,
               [[str(second_raw_id), *pending_replacement]])
    assert ingest_corrections(pending_file, DSN)["row_count"] == 1

    batch_one = promote(DSN, raw_limit=1)
    batch_two = promote(DSN, raw_limit=1)
    assert batch_one["fact_inserted_rows"] == 1
    assert batch_one["correction_events"] == 0
    assert batch_two["fact_inserted_rows"] == 1
    assert batch_two["correction_events"] == 1
    assert promote(DSN)["status"] == "skipped"

    with psycopg.connect(DSN) as conn:
        original_id = conn.execute(
            "SELECT raw_record_id FROM raw.transaction_record "
            "WHERE file_id=%s AND source_row_number=2", (source_result["file_id"],),
        ).fetchone()[0]
        old_fact = conn.execute(
            "SELECT transaction_key, amount_paid FROM core.fact_transaction "
            "WHERE source_raw_record_id=%s", (original_id,),
        ).fetchone()

    older = ["2020/01/01 08:00", "004", f"D{unique}", "005", f"E{unique}",
             "10.00", "US Dollar", "10.00", "US Dollar", "Cheque", "0"]
    late_file = tmp_path / "late_Trans.csv"
    _write_csv(late_file, HEADERS, [older])
    late_result = ingest_file(late_file, DSN)
    assert late_result["accepted_rows"] == 1
    late_batch = promote(DSN)
    assert late_batch["late_arriving_rows"] == 1
    assert late_batch["fact_inserted_rows"] == 1

    replacement = first.copy()
    replacement[1] = "009"
    replacement[5] = "999.00"
    replacement[7] = "999.00"
    correction_file = tmp_path / "corrections.csv"
    _write_csv(correction_file, CORRECTION_HEADER,
               [[str(original_id), *replacement]])
    correction_result = ingest_corrections(correction_file, DSN)
    assert correction_result["row_count"] == 1
    assert ingest_corrections(correction_file, DSN)["status"] == "skipped"
    correction_batch = promote(DSN)
    assert correction_batch["correction_events"] == 1
    assert correction_batch["corrected_transactions"] == 1

    with psycopg.connect(DSN) as conn:
        corrected = conn.execute(
            "SELECT f.transaction_key, f.amount_paid, f.current_correction_id, "
            "b.bank_code FROM core.fact_transaction f "
            "JOIN core.dim_account a ON a.account_key=f.from_account_key "
            "JOIN core.dim_bank b ON b.bank_key=a.bank_key "
            "WHERE f.source_raw_record_id=%s", (original_id,),
        ).fetchone()
        original_amount = conn.execute(
            "SELECT payload->>'amount_paid' FROM raw.transaction_record "
            "WHERE raw_record_id=%s", (original_id,),
        ).fetchone()[0]
    assert corrected[0] == old_fact[0]
    assert str(corrected[1]) == "999.00"
    assert corrected[2] is not None
    assert corrected[3] == "009"
    assert original_amount == "125.50"

    newer_replacement = replacement.copy()
    newer_replacement[5] = "777.00"
    newer_replacement[7] = "777.00"
    newer_file = tmp_path / "newer_corrections.csv"
    _write_csv(newer_file, CORRECTION_HEADER,
               [[str(original_id), *newer_replacement]])
    ingest_corrections(newer_file, DSN)
    assert promote(DSN)["corrected_transactions"] == 1
    # Replaying an older correction must not overwrite the later event.
    old_correction_replay = promote(
        DSN, mode="backfill", correction_after=corrected[2] - 1,
        correction_through=corrected[2],
    )
    assert old_correction_replay["corrected_transactions"] == 0
    with psycopg.connect(DSN) as conn:
        watermark_before = conn.execute(
            "SELECT last_raw_record_id, last_correction_id FROM ops.pipeline_state "
            "WHERE pipeline_name='transaction_promotion'"
        ).fetchone()

    replay = promote(DSN, mode="backfill", raw_after=original_id - 1,
                     raw_through=original_id)
    assert replay["status"] == "completed"
    assert replay["fact_inserted_rows"] == 0
    with psycopg.connect(DSN) as conn:
        watermark_after = conn.execute(
            "SELECT last_raw_record_id, last_correction_id FROM ops.pipeline_state "
            "WHERE pipeline_name='transaction_promotion'"
        ).fetchone()
        final_fact = conn.execute(
            "SELECT amount_paid FROM core.fact_transaction WHERE source_raw_record_id=%s",
            (original_id,),
        ).fetchone()[0]
    assert watermark_after == watermark_before
    assert str(final_fact) == "777.00"

    with pytest.raises(psycopg.Error, match="backfill range exceeds"):
        promote(DSN, mode="backfill", raw_after=0, raw_through=999999999999)
    with psycopg.connect(DSN) as conn:
        failure = conn.execute(
            "SELECT requested_mode, error_message FROM ops.promotion_failure "
            "ORDER BY promotion_failure_id DESC LIMIT 1"
        ).fetchone()
        state_after_failure = conn.execute(
            "SELECT last_raw_record_id, last_correction_id FROM ops.pipeline_state "
            "WHERE pipeline_name='transaction_promotion'"
        ).fetchone()
    assert failure[0] == "backfill"
    assert "backfill range exceeds" in failure[1]
    assert state_after_failure == watermark_before
