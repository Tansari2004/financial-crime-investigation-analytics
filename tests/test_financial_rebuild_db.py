"""Bounded rebuild must agree with primary PostgreSQL feature semantics."""
import csv
from datetime import datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


@pytest.mark.skipif(not os.getenv("FINANCIAL_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_bounded_features_match_postgresql_and_source_order(tmp_path):
    import psycopg
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source.csv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Timestamp", "From Bank", "Account", "To Bank", "Account", "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency", "Payment Format", "Is Laundering"])
        for day in range(18):
            for i in range(10):
                amount = f"{i + 1}.025852"
                writer.writerow([(datetime(2022, 9, 1) + timedelta(days=day, hours=i)).strftime("%Y/%m/%d %H:%M"),
                                 "1", f"A{i % 3}", "2", f"B{i}", amount, "Bitcoin", amount, "Bitcoin",
                                 "Wire" if i % 2 else "ACH", int(i % 4 == 0)])
    schema = "rebuild_" + uuid4().hex[:12]
    with psycopg.connect(os.environ["FINANCIAL_TEST_DATABASE_URL"]) as conn:
        try:
            conn.execute(f'CREATE SCHEMA "{schema}"')
            conn.execute(f'SET LOCAL search_path TO "{schema}"')
            conn.execute((root / "sql/schema.sql").read_text())
            with conn.cursor().copy("COPY transactions(transaction_time,from_bank,from_account,to_bank,to_account,amount_received,receiving_currency,amount_paid,payment_currency,payment_format,is_laundering) FROM STDIN WITH (FORMAT CSV,HEADER TRUE)") as copy:
                copy.write(source.read_bytes())
            conn.execute((root / "sql/model_features.sql").read_text())
            cursor = conn.execute("SELECT * FROM model_features ORDER BY transaction_id")
            expected = pd.DataFrame(cursor.fetchall(), columns=[field.name for field in cursor.description])
        finally:
            conn.rollback()
    output = tmp_path / "bounded"
    subprocess.run([sys.executable, str(root / "scripts/rebuild_financial_bounded.py"),
                    "--source", str(source), "--output", str(output)], check=True, cwd=root)
    actual = pd.read_csv(output / "model_features.csv.gz", parse_dates=["transaction_time"])
    assert_frame_equal(expected, actual, check_dtype=False, rtol=1e-12, atol=1e-12)
