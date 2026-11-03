"""Re-import original decimal values and rebuild features in an EMPTY database.

Never alters or overwrites an existing modelling table. The caller supplies a
new database; original source data and old experiment artifacts remain intact.
"""
import argparse
import hashlib
import json
from pathlib import Path

import psycopg
from financial_crime.train_model import file_sha256

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/full_precision")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    features = args.output / "model_features.csv"
    evidence = args.output / "precision_import.json"
    if features.exists() or evidence.exists():
        raise ValueError("Use a new output directory; prior experiment files are preserved")
    digest = hashlib.sha256()
    with args.source.open("rb") as file:
        while block := file.read(1024 * 1024):
            digest.update(block)
    with psycopg.connect(args.database_url) as conn:
        if conn.execute("SELECT to_regclass('transactions'),to_regclass('model_features')").fetchone() != (None, None):
            raise ValueError("Target database is not empty; create a fresh database")
        conn.execute((ROOT / "sql/schema.sql").read_text())
        with conn.cursor().copy("COPY transactions(transaction_time,from_bank,from_account,to_bank,to_account,amount_received,receiving_currency,amount_paid,payment_currency,payment_format,is_laundering) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)") as copy:
            with args.source.open("rb") as file:
                while block := file.read(1024 * 1024):
                    copy.write(block)
        rows, paid, received = conn.execute("SELECT count(*),count(*) FILTER (WHERE amount_paid != round(amount_paid,2)),count(*) FILTER (WHERE amount_received != round(amount_received,2)) FROM transactions").fetchone()
        conn.execute((ROOT / "sql/model_features.sql").read_text())
        with features.open("xb") as target:
            with conn.cursor().copy("COPY (SELECT * FROM model_features ORDER BY transaction_id) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)") as copy:
                for block in copy:
                    target.write(block)
    evidence.write_text(json.dumps({"source_sha256": digest.hexdigest(), "source_bytes": args.source.stat().st_size,
                                   "rows": rows, "paid_rows_with_more_than_two_decimal_precision": paid,
                                   "received_rows_with_more_than_two_decimal_precision": received,
                                   "import_amount_type": "unconstrained PostgreSQL NUMERIC",
                                   "features_amount_type": "double precision for model computation; original database decimals retained",
                                   "features_sha256": file_sha256(features)}, indent=2) + "\n")
    print(json.dumps({"rows": rows, "precision_import": str(evidence)}))


if __name__ == "__main__":
    main()
