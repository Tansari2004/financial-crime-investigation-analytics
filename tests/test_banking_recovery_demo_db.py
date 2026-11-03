"""The demonstration must clean up its own DB even when a check fails."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

DSN = os.environ.get("BANKING_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set BANKING_TEST_DATABASE_URL")


def test_failed_demo_never_uses_admin_database_and_cleans_up(tmp_path, monkeypatch):
    import psycopg
    path = Path(__file__).parents[1] / "scripts/demo_banking_recovery.py"
    spec = importlib.util.spec_from_file_location("recovery_demo", path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    with psycopg.connect(DSN) as conn:
        admin_database = conn.execute("SELECT current_database()").fetchone()[0]
        before = conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'banking_demo_%' ORDER BY datname").fetchall()

    def interrupted(dsn, output):
        with psycopg.connect(dsn) as conn:
            database = conn.execute("SELECT current_database()").fetchone()[0]
        assert database.startswith("banking_demo_") and database != admin_database
        demo.bootstrap(dsn)
        from banking_pipeline.health import read_health
        with psycopg.connect(dsn) as conn:
            empty = read_health(conn)
        assert empty["status"] == "NO DATA"
        assert empty["latest_file_ingestion_seconds"] is None
        assert empty["latest_successful_publication_utc"] is None
        raise RuntimeError("simulated failed demonstration check")

    monkeypatch.setattr(demo, "run_demo", interrupted)
    monkeypatch.setattr(sys, "argv", [str(path), "--admin-dsn", DSN,
                                      "--output-dir", str(tmp_path)])
    # An old passing artifact must not survive a failed rerun as current proof.
    (tmp_path / "report.json").write_text('{"status": "passed"}')
    with pytest.raises(RuntimeError, match="simulated failed"):
        demo.main()
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "failed"
    with psycopg.connect(DSN) as conn:
        after = conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'banking_demo_%' ORDER BY datname").fetchall()
    assert after == before


def test_health_separates_source_acceptance_from_publication():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from uuid import uuid4
    from banking_pipeline.bootstrap import bootstrap
    from banking_pipeline.health import read_health
    from banking_pipeline.ingest import ingest_file
    from banking_pipeline.promote import promote
    from banking_pipeline.analytics import publish
    database = "health_test_" + uuid4().hex
    options = conninfo_to_dict(DSN)
    options["dbname"] = database
    dsn = make_conninfo(**options)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        bootstrap(dsn)
        ingest_file(Path(__file__).parent / "fixtures/clean_pipeline_Trans.csv", dsn)
        with psycopg.connect(dsn) as conn:
            accepted = read_health(conn)
        assert accepted["status"] == "AWAITING PROMOTION"
        assert accepted["accepted_rows"] == 5 and accepted["published_rows"] == 0
        assert accepted["latest_file_ingestion_seconds"] >= 0
        while promote(dsn)["status"] != "skipped":
            pass
        with psycopg.connect(dsn) as conn:
            assert read_health(conn)["status"] == "AWAITING PUBLICATION"
        publish(dsn)
        with psycopg.connect(dsn) as conn:
            published = read_health(conn)
        assert published["status"] == "PUBLISHED" and published["published_rows"] == 5
        assert published["latest_successful_publication_utc"] is not None
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
