"""The legacy modelling schema must preserve values before feature extraction."""
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.skipif(not os.getenv("FINANCIAL_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_original_decimal_survives_import_and_prior_history():
    import psycopg
    root = Path(__file__).resolve().parents[1]
    schema = "precision_" + uuid4().hex[:12]
    with psycopg.connect(os.environ["FINANCIAL_TEST_DATABASE_URL"]) as conn:
        # Transaction rollback removes this test's schema, including on error.
        try:
            conn.execute(f'CREATE SCHEMA "{schema}"')
            conn.execute(f'SET LOCAL search_path TO "{schema}"')
            conn.execute((root / "sql/schema.sql").read_text())
            with conn.cursor().copy("COPY transactions(transaction_time,from_bank,from_account,to_bank,to_account,amount_received,receiving_currency,amount_paid,payment_currency,payment_format,is_laundering) FROM STDIN WITH (FORMAT CSV)") as copy:
                copy.write("2022-09-01 09:00,1,A,2,B,0.025852,Bitcoin,0.025852,Bitcoin,Wire,0\n2022-09-02 09:00,1,A,2,B,0.00123456789,Bitcoin,0.00123456789,Bitcoin,Wire,1\n")
            assert conn.execute("SELECT amount_paid FROM transactions ORDER BY transaction_id").fetchall() == [(Decimal("0.025852"),), (Decimal("0.00123456789"),)]
            conn.execute((root / "sql/model_features.sql").read_text())
            assert conn.execute("SELECT prior_average_amount FROM model_features WHERE transaction_id=2").fetchone()[0] == pytest.approx(.025852)
        finally:
            conn.rollback()
