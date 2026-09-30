"""Run with BANKING_TEST_DATABASE_URL pointing at a disposable PostgreSQL database."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from banking_pipeline.ingest import ingest_file


@pytest.mark.skipif(not os.environ.get("BANKING_TEST_DATABASE_URL"),
                    reason="set BANKING_TEST_DATABASE_URL for PostgreSQL integration test")
def test_ingest_quarantine_and_idempotency(tmp_path: Path) -> None:
    import psycopg

    dsn = os.environ["BANKING_TEST_DATABASE_URL"]
    ddl = (Path(__file__).parents[1] / "pipeline/sql/001_foundation.sql").read_text()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(ddl)

    fixture = (Path(__file__).parent / "fixtures/pipeline_transactions.csv").read_text()
    path = tmp_path / "unique_Trans.csv"
    path.write_text(fixture.replace("A001", uuid4().hex), encoding="utf-8")

    first = ingest_file(path, dsn, batch_size=2)
    assert first["status"] == "completed"
    assert (first["total_rows"], first["accepted_rows"],
            first["rejected_rows"], first["duplicate_candidates"]) == (7, 2, 4, 1)
    second = ingest_file(path, dsn, batch_size=2)
    assert second["status"] == "skipped"
    assert second["file_id"] == first["file_id"]

    with psycopg.connect(dsn) as conn:
        raw_count = conn.execute(
            "SELECT count(*) FROM raw.transaction_record WHERE file_id=%s",
            (first["file_id"],),
        ).fetchone()[0]
        quarantine_count = conn.execute(
            "SELECT count(*) FROM quarantine.rejected_record WHERE file_id=%s",
            (first["file_id"],),
        ).fetchone()[0]
    assert (raw_count, quarantine_count) == (7, 5)

    bad_path = tmp_path / "bad_Trans.csv"
    bad_path.write_text(f"bad,header\n{uuid4().hex},broken\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header_mismatch"):
        ingest_file(bad_path, dsn)
    with psycopg.connect(dsn) as conn:
        failed = conn.execute(
            "SELECT status, total_rows, error_message FROM ops.file_manifest "
            "WHERE source_path=%s", (str(bad_path.resolve()),),
        ).fetchone()
    assert failed[0] == "failed"
    assert failed[1] == 0
    assert "header_mismatch" in failed[2]
