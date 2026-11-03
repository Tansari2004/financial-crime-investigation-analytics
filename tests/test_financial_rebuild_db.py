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
@pytest.mark.parametrize("rounded_control", [False, True])
def test_bounded_features_match_postgresql_and_source_order(tmp_path, rounded_control):
    import psycopg
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source.csv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Timestamp", "From Bank", "Account", "To Bank", "Account", "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency", "Payment Format", "Is Laundering"])
        for day in range(18):
            for i in range(10):
                currency = "Bitcoin" if i % 2 else "US Dollar"
                amount = f"{i + 1}.025852" if i % 2 else f"{i + 1}.03"
                writer.writerow([(datetime(2022, 9, 1) + timedelta(days=day, hours=i)).strftime("%Y/%m/%d %H:%M"),
                                 "1", f"A{i % 3}", "2", f"B{i}", amount, currency, amount, currency,
                                 "Wire" if i % 2 else "ACH", int(i % 4 == 0)])
    schema = "rebuild_" + uuid4().hex[:12]
    with psycopg.connect(os.environ["FINANCIAL_TEST_DATABASE_URL"]) as conn:
        try:
            conn.execute(f'CREATE SCHEMA "{schema}"')
            conn.execute(f'SET LOCAL search_path TO "{schema}"')
            schema_sql = (root / "sql/schema.sql").read_text()
            if rounded_control:
                schema_sql = schema_sql.replace("amount_received NUMERIC,", "amount_received NUMERIC(18,2),").replace("amount_paid NUMERIC,", "amount_paid NUMERIC(18,2),")
            conn.execute(schema_sql)
            with conn.cursor().copy("COPY transactions(transaction_time,from_bank,from_account,to_bank,to_account,amount_received,receiving_currency,amount_paid,payment_currency,payment_format,is_laundering) FROM STDIN WITH (FORMAT CSV,HEADER TRUE)") as copy:
                copy.write(source.read_bytes())
            conn.execute((root / "sql/model_features.sql").read_text())
            cursor = conn.execute("SELECT * FROM model_features ORDER BY transaction_id")
            expected = pd.DataFrame(cursor.fetchall(), columns=[field.name for field in cursor.description])
        finally:
            conn.rollback()
    output = tmp_path / "bounded"
    command = [sys.executable, str(root / "scripts/rebuild_financial_bounded.py"),
               "--source", str(source), "--output", str(output)]
    if rounded_control:
        command.append("--rounded-control")
    subprocess.run(command, check=True, cwd=root)
    actual = pd.read_csv(output / "model_features.csv.gz", parse_dates=["transaction_time"])
    assert_frame_equal(expected, actual, check_dtype=False, rtol=1e-12, atol=1e-12)
