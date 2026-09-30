"""Scheduled job behavior with a quality failure and atomic publication."""

import csv
import os
from pathlib import Path
from uuid import uuid4

import pytest

from banking_pipeline.bootstrap import bootstrap
from banking_pipeline.contract import HEADERS


DSN = os.environ.get("BANKING_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set BANKING_TEST_DATABASE_URL")


def _write(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        writer.writerows(rows)


def test_dagster_job_publishes_or_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    import psycopg

    from banking_pipeline.orchestration import defs

    bootstrap(DSN)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.quality_policy SET max_rejected_fraction=1 "
            "WHERE policy_name='transaction_files'"
        )
    monkeypatch.setenv("BANKING_DATABASE_URL", DSN)
    monkeypatch.setenv("BANKING_SOURCE_DIR", str(tmp_path))
    monkeypatch.delenv("BANKING_CORRECTION_DIR", raising=False)
    marker = uuid4().hex[:12]
    good = ["2032/01/01 09:00", "001", f"A{marker}", "002", f"B{marker}",
            "5.00", "US Dollar", "5.00", "US Dollar", "Wire", "0"]
    _write(tmp_path / "good_Trans.csv", [good])

    job = defs.resolve_job_def("banking_daily_pipeline")
    assert job.execute_in_process().success
    with psycopg.connect(DSN) as conn:
        published_before = conn.execute(
            "SELECT last_publication_id FROM analytics.publication_state WHERE state_id=1"
        ).fetchone()[0]
        daily_count = conn.execute(
            "SELECT COALESCE(sum(transaction_count),0) "
            "FROM analytics.fact_daily_transaction WHERE event_date='2032-01-01'"
        ).fetchone()[0]
    assert daily_count >= 1
    assert job.execute_in_process().success

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE ops.quality_policy SET max_rejected_fraction=0.05 "
            "WHERE policy_name='transaction_files'"
        )
    bad = good.copy()
    bad[0] = "invalid-date"
    bad[2] = f"C{marker}"
    _write(tmp_path / "bad_Trans.csv", [good[:2] + [f"X{marker}"] + good[3:], bad])
    failed = job.execute_in_process(raise_on_error=False)
    assert not failed.success
    with psycopg.connect(DSN) as conn:
        published_after = conn.execute(
            "SELECT last_publication_id FROM analytics.publication_state WHERE state_id=1"
        ).fetchone()[0]
        error = conn.execute(
            "SELECT error_message FROM ops.analytics_failure "
            "ORDER BY analytics_failure_id DESC LIMIT 1"
        ).fetchone()[0]
    assert published_after == published_before
    assert "rejected-row fraction" in error
