"""Bitcoin amounts must survive every layer without rounding or quarantine."""

import csv
import os
from decimal import Decimal
from uuid import uuid4

import pytest

from banking_pipeline.analytics import publish
from banking_pipeline.bootstrap import bootstrap
from banking_pipeline.contract import HEADERS
from banking_pipeline.ingest import ingest_file
from banking_pipeline.promote import promote


DSN = os.environ.get("BANKING_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set BANKING_TEST_DATABASE_URL")


def test_bitcoin_amount_survives_full_pipeline(tmp_path):
    import psycopg

    bootstrap(DSN)
    marker = uuid4().hex[:12]
    path = tmp_path / "bitcoin_Trans.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        writer.writerow(["2035/01/01 09:00", f"B{marker}", "A1", f"C{marker}",
                         "A2", "0.025852", "Bitcoin", "0.025852", "Bitcoin",
                         "Wire", "0"])
    loaded = ingest_file(path, DSN)
    assert loaded["accepted_rows"] == 1
    assert loaded["rejected_rows"] == 0
    assert promote(DSN)["status"] == "completed"
    with psycopg.connect(DSN, autocommit=True) as conn:
        original_policy = conn.execute(
            "SELECT max_rejected_fraction FROM ops.quality_policy "
            "WHERE policy_name='transaction_files'"
        ).fetchone()[0]
        # Other integration tests deliberately leave a high-rejection fixture
        # unpublished in this shared test database.
        conn.execute(
            "UPDATE ops.quality_policy SET max_rejected_fraction=1 "
            "WHERE policy_name='transaction_files'"
        )
    try:
        assert publish(DSN)["status"] == "published"
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                "UPDATE ops.quality_policy SET max_rejected_fraction=%s "
                "WHERE policy_name='transaction_files'", (original_policy,),
            )
    with psycopg.connect(DSN) as conn:
        amount = conn.execute(
            "SELECT paid_amount FROM analytics.v_daily_metrics "
            "WHERE event_date='2035-01-01' AND from_bank_code=%s",
            (f"B{marker}",),
        ).fetchone()[0]
        mismatches = conn.execute(
            "SELECT count(*) FROM analytics.file_amount_reconciliation "
            "WHERE file_id=%s AND (raw_staging_delta<>0 OR effective_core_delta<>0)",
            (loaded["file_id"],),
        ).fetchone()[0]
    assert amount == Decimal("0.025852")
    assert mismatches == 0
